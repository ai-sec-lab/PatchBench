import os
import time
import sys
import json
import threading
import argparse
from git import Repo
import shutil
import subprocess
from pathlib import Path
from constants import *


# Total dollar budget allowed for a single run. The process is killed once the
# cost crosses this value.
BUDGET_LIMIT = 30
# A diff snapshot is taken every time the cost crosses a multiple of this value.
COST_STEP = 5
# How often (in seconds) the cost monitor polls the session token usage. A
# smaller interval reduces how far the cost can overshoot a snapshot threshold
# between two polls.
POLL_INTERVAL_SECONDS = 15


class CodexSnapshotRunner:
    def __init__(self, model_name):
        self.log_dir = f"/.codex/"
        os.makedirs(self.log_dir, exist_ok=True)

        # Codex only works with OpenAI models
        self.model_name = model_name

    @staticmethod
    def init(repo_dir):
        shutil.rmtree(f"{repo_dir}/.git")
        repo = Repo.init(repo_dir)
        return repo

    @staticmethod
    def commit(repo: Repo, file=None):
        msg = f"Auto-commit on {time.strftime('%Y-%m-%d %H:%M:%S')}"
        repo.git.commit("--allow-empty", "--no-verify", "-m", msg)
        return repo.head.commit.hexsha

    @staticmethod
    def diff_between(repo: Repo, base_sha: str, head_sha: str):
        cmd = [
            "git", "diff", base_sha, head_sha,
        ]

        patch_text = repo.git.execute(
            cmd,
            stdout_as_string=True,
            strip_newline_in_stdout=False,   # <-- key bit
        )

        return patch_text

    @staticmethod
    def _parse_file_changes(line):
        """Return the list of changed paths reported by a single JSON event line.

        Mirrors the parsing in ``get_file_changed`` but operates on a single
        line so it can be consumed while codex is still running.
        """
        line = line.strip()
        if not line:
            return []
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            # if anything non-JSON leaks into stdout, ignore it
            return []

        if evt.get("type") == "item.completed":
            item = evt.get("item", {})
            if item.get("type") == "file_change":
                return [ch.get("path", "") for ch in item.get("changes", [])]
        return []

    @staticmethod
    def get_file_changed(stdout):
        changes = []
        for line in stdout.splitlines():
            changes.extend(CodexSnapshotRunner._parse_file_changes(line))
        changes = list(set(changes))
        return changes

    def run(self, id, repo_folder, out_base):
        """Run codex and take a diff snapshot every ``COST_STEP`` dollars.

        Returns ``(final_diff, budget_exhausted)``. ``final_diff`` is always the
        complete ``mask_id..HEAD`` diff and is meant to be written as the plain
        ``.diff`` regardless of how the run ended (it is only ``None`` on an
        early error such as a failed login). ``budget_exhausted`` is True when
        the run was killed for crossing ``BUDGET_LIMIT`` (in which case the
        per-threshold snapshots, including ``_{BUDGET_LIMIT}.diff``, were also
        written).
        """

        repo_base = self.init(repo_folder)
        repo_base.git.add(A=True)
        mask_id = self.commit(repo_base)

        metadata = json.loads(Path("/harnesses/metadata.json").read_text())
        sanitizer_report = metadata[id]["sanitizer_report"]
        project = metadata[id]["project"]

        if NO_BROWSER_FLAG:
            prompt = PROMPT.format(
                project=project,
                repo_folder=repo_folder,
                sanitizer_report=sanitizer_report
            ) + NO_BROWSER_PROMPT
        else:
            prompt = PROMPT.format(
                project=project,
                repo_folder=repo_folder,
                sanitizer_report=sanitizer_report
            )

        login_cmd = "printenv OPENAI_API_KEY | codex login --with-api-key"
        result = subprocess.run(login_cmd, shell=True, check=False)
        if result.returncode:
            print("Login unsuccessful!", flush=True)
            return None, False

        print(prompt)

        run_cmd = [
            "codex",
            "--ask-for-approval", "never",
            "exec",
            "--json",
            "--model", self.model_name,
            "--config", 'model_reasoning_effort="medium"',
            "--config", 'web_search="disabled"',
            "--cd", repo_folder,
            "--sandbox", "danger-full-access",
            prompt,
        ]

        def _read_token_usage(path):
            with open(path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()

            for raw in reversed(lines):
                raw = raw.strip()
                if not raw:
                    continue
                record = json.loads(raw)
                if "type" in record["payload"] and record["payload"]["type"] == "token_count":
                    info = record["payload"]["info"]
                    return info["total_token_usage"]
            return None

        def _collect_latest_token_usage():
            home = os.path.expanduser("~")
            sessions_dir = os.path.join(home, ".codex", "sessions")
            if not os.path.isdir(sessions_dir):
                return None

            result = subprocess.run(
                ["find", sessions_dir, "-type", "f",
                    "-name", "rollout*.jsonl", "-print0"],
                check=False,
                capture_output=True,
            )
            paths = [p.decode("utf-8")
                     for p in result.stdout.split(b"\0") if p]

            latest_usage = None
            for src in paths:
                usage = _read_token_usage(src)
                if usage is not None:
                    latest_usage = usage
                    break
            return latest_usage

        # Shared state between the reader, monitor and main threads.
        changed_files = set()
        files_lock = threading.Lock()
        stdout_lines = []

        monitor_stop_event = threading.Event()
        budget_exhausted = threading.Event()

        # Snapshot thresholds: 5, 10, ..., BUDGET_LIMIT.
        thresholds = list(range(COST_STEP, BUDGET_LIMIT + 1, COST_STEP))

        def _stage_changed_files():
            with files_lock:
                files = list(changed_files)
            for f in files:
                if f.startswith(repo_folder):
                    try:
                        repo_base.git.add(f)
                    except Exception as e:
                        print(
                            f"Error occurred while adding file {f}: {e}", flush=True)

        def _take_snapshot(threshold):
            """Commit the currently-known changes and write a snapshot diff."""
            _stage_changed_files()
            self.commit(repo_base)
            diff = self.diff_between(repo_base, mask_id, "HEAD")
            snapshot_path = f"{out_base}_{threshold}.diff"
            Path(snapshot_path).write_text(diff, errors="ignore")
            print(f"Snapshot at {threshold} dollars saved to {snapshot_path}",
                  flush=True)

        def _read_stdout(proc):
            # Stream codex's JSON output so file changes can be tracked while it
            # is still running (needed for mid-run snapshots).
            for line in proc.stdout:
                stdout_lines.append(line)
                paths = self._parse_file_changes(line)
                if paths:
                    with files_lock:
                        changed_files.update(paths)

        def _monitor_usage(proc):
            next_idx = 0  # index into `thresholds` of the next snapshot to take
            while not monitor_stop_event.is_set():
                if proc.poll() is not None:
                    break
                usage = _collect_latest_token_usage()

                if usage is not None:
                    pricing = MODEL_PRICING[self.model_name]
                    uncached = usage["input_tokens"] - usage["cached_input_tokens"]
                    cost = (uncached * pricing["input"]
                            + usage["cached_input_tokens"] * pricing["cached_input"]
                            + usage["output_tokens"] * pricing["output"]) / 1e6

                    print(f"Current usage: {cost:.2f} dollars", flush=True)

                    # Take a snapshot for every threshold the cost has crossed.
                    # A single poll may cross several thresholds at once.
                    while next_idx < len(thresholds) and cost >= thresholds[next_idx]:
                        threshold = thresholds[next_idx]
                        _take_snapshot(threshold)
                        next_idx += 1

                        if threshold >= BUDGET_LIMIT:
                            budget_exhausted.set()
                            if proc.poll() is None:
                                proc.kill()
                            break

                    if budget_exhausted.is_set():
                        break
                else:
                    print("Conversation not start yet!", flush=True)
                    print(f"Current usage: 0 dollars", flush=True)

                if monitor_stop_event.wait(POLL_INTERVAL_SECONDS):
                    break

        # Run with concurrent stdout streaming and token monitoring.
        proc = subprocess.Popen(run_cmd,
                                stderr=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                text=True,
                                errors="ignore",
                                shell=False)

        reader_thread = threading.Thread(
            target=_read_stdout, args=(proc,), daemon=True)
        reader_thread.start()
        monitor_thread = threading.Thread(
            target=_monitor_usage, args=(proc,), daemon=True)
        monitor_thread.start()

        try:
            proc.wait()
        finally:
            monitor_stop_event.set()
            monitor_thread.join()
            reader_thread.join(timeout=30)

        if budget_exhausted.is_set():
            print(
                f"Codex run terminated after exceeding {BUDGET_LIMIT} dollars usage.", flush=True)

        stdout = "".join(stdout_lines).strip()

        print("Conversation history:")
        print(stdout)

        # Persist the session rollout logs (same as the non-snapshot harness).
        home = os.path.expanduser("~")
        sessions_dir = os.path.join(home, ".codex", "sessions")
        dst_dir = os.path.join("/.codex")
        result = subprocess.run(
            ["find", sessions_dir, "-type", "f",
                "-name", "rollout*.jsonl", "-print0"],
            check=False,
            capture_output=True,
        )
        paths = [p.decode("utf-8") for p in result.stdout.split(b"\0") if p]
        for src in paths:
            subprocess.run(["cp", src, dst_dir], check=False)

        # Build the final diff from the complete output and let the caller write
        # the plain .diff. This happens whether the run finished naturally or was
        # killed for exceeding the budget; in the latter case the per-threshold
        # snapshots have already been written too.
        changed_files_final = self.get_file_changed(stdout)
        for f in changed_files_final:
            if f.startswith(repo_folder):
                try:
                    repo_base.git.add(f)
                except Exception as e:
                    print(
                        f"Error occurred while adding file {f}: {e}", flush=True)

        self.commit(repo_base)
        diff = self.diff_between(repo_base, mask_id, "HEAD")
        return diff, budget_exhausted.is_set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-name', type=str)
    parser.add_argument('--sanitizer_report', type=str)
    parser.add_argument('--repo-folder', type=str)
    # parser.add_argument('--changed-file', type=str)
    # Where to write the diff. The host owns the naming scheme.
    parser.add_argument('--out-base', type=str)
    args = parser.parse_args()

    out_base = args.out_base

    client = CodexSnapshotRunner(args.model_name)
    final_diff, budget_exhausted = client.run(
        args.sanitizer_report, args.repo_folder, out_base)

    # Always save a final diff, whether or not the budget was exhausted.
    if final_diff is not None:
        Path(f'{out_base}.diff').write_text(final_diff, errors="ignore")


if __name__ == "__main__":
    main()
