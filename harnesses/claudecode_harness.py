"""Claude Code harness.

Unlike the other agents, Claude Code cannot be installed inside the task image,
so this harness runs on the host: it copies the repository out of the image,
mounts that copy back into a live container, and lets the agent edit on the host
while verifying through ``docker exec``. The output contract is identical to the
container-side harnesses -- a diff at ``{out_base}.diff`` and budget snapshots at
``{out_base}_{threshold}.diff``.
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage
from git import Repo

from constants import *


# Total dollar budget allowed for a single run.
BUDGET_LIMIT = 30
# A diff snapshot is taken every time the cost crosses a multiple of this value.
COST_STEP = 5

C_CPP_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}

#: Tool names whose arguments name a file the agent edited.
WRITE_TOOL_NAMES = {"Write", "Edit", "MultiEdit", "NotebookEdit",
                    "create", "str_replace", "insert", "undo_edit"}
PATH_FIELD_NAMES = {"path", "file_path", "filePath", "target_file",
                    "new_file_path", "old_file_path"}


def run_cmd(cmd, check=True, capture=False):
    """Run a docker command on the host."""
    return subprocess.run(cmd, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None)


class ClaudeCodeRunner:
    """Drives Claude Code against a host copy of the task repository."""

    def __init__(self, model_name, log_dir="/tmp/.claudecode"):
        self.model_name = model_name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        api_key = os.getenv("ANTHROPIC_API_KEY")
        assert api_key is not None, "ANTHROPIC_API_KEY environment variable is not set."
        self.api_env = {"ANTHROPIC_API_KEY": api_key,
                        "CLAUDE_CODE_EFFORT_LEVEL": "high"}

    # -- container lifecycle -------------------------------------------------

    @staticmethod
    def locate_repo(container, project):
        """The project checkout's path inside the image."""
        out = run_cmd(["docker", "exec", container, "bash", "-lc",
                       f"find /src -maxdepth 3 -type d -iname '{project}' | head -n 1"],
                      capture=True).stdout.strip()
        assert out, f"no directory named {project!r} under /src in the image"
        return out

    @classmethod
    def extract_repo(cls, image, container, project, workdir):
        """Copy the repository out of the image and mount the copy back in.

        Returns ``(host_repo, container_repo)``. The agent edits ``host_repo``;
        ``docker exec`` sees the same bytes at ``container_repo``.
        """
        # Start from a clean tree: a previous run may have been interrupted
        # before it could remove its own.
        discard_workdir(workdir)
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

        # First container: locate the checkout and copy it to the host.
        run_cmd(["docker", "rm", "-f", container], check=False)
        run_cmd(["docker", "run", "-dit", "--name", container, image, "bash"])
        container_repo = cls.locate_repo(container, project)
        run_cmd(["docker", "cp", f"{container}:{container_repo}", str(workdir)])
        run_cmd(["docker", "rm", "-f", container], check=False)

        host_repo = workdir / Path(container_repo).name
        assert host_repo.is_dir(), f"copy did not produce {host_repo}"

        # Second container: same image, with the host copy bound over the
        # checkout, so the agent's edits are what `vulpatch compile` builds.
        run_cmd(["docker", "run", "-dit", "--name", container,
                 "-v", f"{host_repo.absolute()}:{container_repo}", image, "bash"])
        return str(host_repo.absolute()), container_repo

    # -- git bookkeeping -----------------------------------------------------

    @staticmethod
    def init(repo_dir):
        """Re-initialise the repo so the diff is against a known empty baseline."""
        git_dir = Path(repo_dir) / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        return Repo.init(repo_dir)

    @staticmethod
    def commit(repo):
        msg = f"Auto-commit on {time.strftime('%Y-%m-%d %H:%M:%S')}"
        repo.git.commit("--allow-empty", "--no-verify", "-m", msg)
        return repo.head.commit.hexsha

    @staticmethod
    def diff_between(repo, base_sha, head_sha):
        return repo.git.execute(["git", "diff", base_sha, head_sha],
                                stdout_as_string=True, strip_newline_in_stdout=False)

    @staticmethod
    def diff_worktree(repo, base_sha):
        return repo.git.execute(["git", "diff", "--binary", base_sha, "--"],
                                stdout_as_string=True, strip_newline_in_stdout=False)

    # -- edited-file discovery ----------------------------------------------

    @staticmethod
    def changed_from_git_status(repo):
        """C/C++ files git sees as modified, relative to the repo root."""
        changed = []
        for line in repo.git.status("--porcelain").splitlines():
            if len(line) < 4:
                continue
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if Path(path).suffix.lower() in C_CPP_EXTENSIONS:
                changed.append(path)
        return sorted(set(changed))

    @classmethod
    def changed_from_chat_history(cls, chat_history, repo_folder):
        """Repo files named by a write tool anywhere in the session log."""
        if not Path(chat_history).exists():
            return []

        def normalize(value):
            if not isinstance(value, str) or not value.strip():
                return None
            candidate = os.path.expanduser(value.strip())
            resolved = os.path.abspath(candidate if os.path.isabs(candidate)
                                       else os.path.join(repo_folder, candidate))
            root = os.path.abspath(repo_folder)
            try:
                if os.path.commonpath([root, resolved]) != root:
                    return None
            except ValueError:
                return None
            return None if resolved.lower().endswith(".md") else resolved

        def paths_in(node, found):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in PATH_FIELD_NAMES:
                        got = normalize(value)
                        if got:
                            found.add(got)
                    paths_in(value, found)
            elif isinstance(node, list):
                for item in node:
                    paths_in(item, found)

        found = set()
        with open(chat_history) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stack = [event]
                while stack:
                    node = stack.pop()
                    if isinstance(node, dict):
                        name = node.get("name") or node.get("tool_name")
                        if isinstance(name, str) and name in WRITE_TOOL_NAMES:
                            paths_in(node, found)
                        stack.extend(node.values())
                    elif isinstance(node, list):
                        stack.extend(node)
        return sorted(found)

    @staticmethod
    def session_log(repo_folder, session_id):
        """Where the Claude CLI stores this session's transcript."""
        slug = lambda v: re.sub(r"[^A-Za-z0-9]", "-", v)  # noqa: E731
        project_dir = Path(f"~/.claude/projects/{slug(os.getcwd())}-{slug(repo_folder)}")
        return project_dir.expanduser() / f"{session_id}.jsonl"

    # -- the run -------------------------------------------------------------

    async def run_async(self, id, image, container, project, workdir, out_base):
        """Returns ``(final_diff, budget_exhausted)``, matching the other harnesses."""
        host_repo, container_repo = self.extract_repo(image, container, project, workdir)

        repo = self.init(host_repo)
        repo.git.add(A=True)
        mask_id = self.commit(repo)

        # This harness only ever runs on the host, so the agent-visible
        # metadata is read from beside the script rather than from the mount.
        metadata = json.loads((Path(__file__).parent / "metadata.json").read_text())
        sanitizer_report = metadata[id]["sanitizer_report"]

        prompt = PROMPT.format(project=project, repo_folder=host_repo,
                               sanitizer_report=sanitizer_report)
        if NO_BROWSER_FLAG:
            prompt += NO_BROWSER_PROMPT
        # The agent edits on the host, so verification has to go through the
        # container. Everything else about the prompt matches the other agents.
        prompt = prompt.replace("`vulpatch compile`",
                                f"`docker exec {container} vulpatch compile`")
        prompt = prompt.replace("`vulpatch run`",
                                f"`docker exec {container} vulpatch run`")
        prompt = prompt.replace(
            "The Proof-of-Concept (PoC) input that reproduces this vulnerability is at /tmp/poc.",
            f"The Proof-of-Concept (PoC) input is at /tmp/poc inside the container "
            f"{container}; the report's \"/src/{project}/...\" paths correspond to "
            f"\"{host_repo}/...\" on disk.")

        thresholds = list(range(COST_STEP, BUDGET_LIMIT + 1, COST_STEP))
        next_idx = 0
        budget_exhausted = False
        spend = 0.0
        counted = {}

        def take_snapshot(threshold):
            path = f"{out_base}_{threshold}.diff"
            Path(path).write_text(self.diff_worktree(repo, mask_id), errors="ignore")
            print(f"Snapshot at {threshold} dollars saved to {path}", flush=True)

        def note_spend(value):
            nonlocal next_idx, spend, budget_exhausted
            spend = value
            print(f"Estimated Claude spend: ${spend:.4f} / ${BUDGET_LIMIT:.2f}", flush=True)
            while next_idx < len(thresholds) and spend >= thresholds[next_idx]:
                take_snapshot(thresholds[next_idx])
                next_idx += 1
            if spend >= BUDGET_LIMIT:
                budget_exhausted = True

        options = ClaudeAgentOptions(
            model=self.model_name,
            permission_mode="default",
            cwd=host_repo,
            env=self.api_env,
            allowed_tools=["Read", "Write", "Edit", "Bash"],
            disallowed_tools={"Bash(rm*)", "Bash(docker rmi*)",
                              "Bash(docker image rm*)", "WebSearch", "WebFetch"},
            max_budget_usd=BUDGET_LIMIT,
        )

        session_id = None
        chat_history = self.log_dir / "claudecode-chat-log.jsonl"
        try:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    print(message, flush=True)
                    if isinstance(message, ResultMessage):
                        session_id = message.session_id
                        if message.total_cost_usd is not None:
                            note_spend(message.total_cost_usd)
                        print(message.result, flush=True)
                        continue
                    usage = getattr(message, "usage", None)
                    mid = getattr(message, "message_id", None)
                    cost = getattr(message, "total_cost_usd", None)
                    if mid and cost is not None and counted.get(mid) != cost:
                        counted[mid] = cost
                        note_spend(sum(counted.values()))

            if session_id:
                source = self.session_log(host_repo, session_id)
                if source.exists():
                    shutil.copy(source, chat_history)
                else:
                    print(f"Claude chat history not found: {source}", flush=True)
        finally:
            # `vulpatch compile` runs as root inside the container and writes
            # build artifacts into the bind mount, so the checkout has to be
            # handed back before the container -- and with it root -- is gone.
            run_cmd(["docker", "exec", container, "chown", "-R",
                     f"{os.getuid()}:{os.getgid()}", container_repo], check=False)
            run_cmd(["docker", "rm", "-f", container], check=False)

        changed = self.changed_from_chat_history(chat_history, host_repo)
        if not changed:
            print("No files from chat history; falling back to git status.", flush=True)
            changed = self.changed_from_git_status(repo)
        if not changed:
            print("No files were changed by Claude Code.", flush=True)

        for path in changed:
            try:
                repo.git.add(path)
            except Exception as e:  # noqa: BLE001 - one bad path must not lose the rest
                print(f"Error adding {path}: {e}", flush=True)

        self.commit(repo)
        return self.diff_between(repo, mask_id, "HEAD"), budget_exhausted

    def run(self, *args, **kwargs):
        return asyncio.run(self.run_async(*args, **kwargs))


def discard_workdir(workdir):
    """Remove the extracted checkout. A no-op unless it is a real directory.

    Refuses to follow a symlink, so a mis-set ``--workdir`` cannot delete
    something outside the scratch tree.
    """
    path = Path(workdir)
    if not path.is_dir() or path.is_symlink():
        return
    try:
        shutil.rmtree(path)
    except OSError as e:
        # Never fatal: the diff is already written, and a tree left behind is
        # a disk-space problem rather than a correctness one.
        print(f"Could not remove working copy {path}: {e}", flush=True)
        return
    print(f"Removed working copy {path}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-name', type=str)
    parser.add_argument('--sanitizer_report', type=str)  # the task id
    # Where to write the diff. The host owns the naming scheme.
    parser.add_argument('--out-base', type=str)
    parser.add_argument('--image', type=str)
    parser.add_argument('--container', type=str)
    parser.add_argument('--project', type=str)
    parser.add_argument('--workdir', type=str)
    parser.add_argument('--log-dir', type=str, default='/tmp/.claudecode')
    args = parser.parse_args()

    client = ClaudeCodeRunner(args.model_name, args.log_dir)
    final_diff, budget_exhausted = client.run(
        args.sanitizer_report, args.image, args.container,
        args.project, args.workdir, args.out_base)

    # Always save a final diff, whether or not the budget was exhausted.
    if final_diff is not None:
        out = Path(f'{args.out_base}.diff')
        out.write_text(final_diff, errors="ignore")
        # The extracted checkout is only discarded once the patch derived from
        # it is verifiably on disk.
        if final_diff and not out.stat().st_size:
            raise RuntimeError(f"{out} is empty but the run produced a diff")
        discard_workdir(args.workdir)


if __name__ == "__main__":
    main()
