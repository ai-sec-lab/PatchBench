"""Base class and command line shared by the agent harnesses."""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path

from git import Repo

from constants import (C_CPP_EXTENSIONS, DEFAULT_EFFORT, EFFORT_LEVELS,
                       NO_BROWSER_FLAG, NO_BROWSER_PROMPT, PROMPT)

#: Dollar budget for one run. The agent is stopped once spend crosses this.
BUDGET_LIMIT = 50
#: A diff snapshot is written each time spend crosses a multiple of this.
#: None turns snapshots off.
COST_STEP = None

#: The unprivileged user the agent program runs as (see agent/Dockerfile).
AGENT_USER = "agent"
#: The agent's home. Shared with the task container, like the task's folders.
AGENT_HOME = "/root"
#: Folders that hold the same files in both containers. File tools may only
#: touch these; anything else would be the agent container's own files.
SHARED_ROOTS = ("/src", "/out", "/tmp", AGENT_HOME)
#: Where root here reaches the shared folders without the agent's view (see agent/view).
DISK = "/opt/patchbench/disk"
#: Provider keys the inference stage may pass in (constants.MODEL_API_KEYS).
API_KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")

# Read by agent/shell and agent/forward, which send each command to the task container.
FORWARD = "/opt/patchbench/libexec/forward"
VIEW = "/opt/patchbench/libexec/view"
DOCKER = "/usr/local/bin/docker"
TASK_CONTAINER_FILE = "/opt/patchbench/task-container"
BASE_ENV_FILE = "/opt/patchbench/agent-base-env"
BASE_PATH_FILE = "/opt/patchbench/agent-base-path"


class AgentUnavailable(RuntimeError):
    """The agent could not be started at all, so there is no patch to record."""


class AgentHarness(ABC):
    """One agent run on one task."""

    #: The agent's name, as in ``<name>_harness.py`` and ``agent/install/<name>.sh``.
    name: str = ""

    def __init__(self, model_name: str, task_id: str, repo_folder: str,
                 out_base: str, log_dir: str, effort: str = DEFAULT_EFFORT) -> None:
        self.model_name = model_name
        self.task_id = task_id
        #: Effort level for agents that take one (Claude Code).
        self.effort = effort
        self.repo_folder = os.path.abspath(repo_folder)
        self.out_base = out_base
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        meta = json.loads((Path(__file__).parent / "metadata.json").read_text())
        self.project = meta[task_id]["project"]
        self.sanitizer_report = meta[task_id]["sanitizer_report"]

        self.repo: Repo | None = None
        self.mask_id = ""
        self.budget_exhausted = False
        self._thresholds = (list(range(COST_STEP, BUDGET_LIMIT + 1, COST_STEP))
                            if COST_STEP else [])
        self._next_threshold = 0

    # -- agent interface ----------------------------------------------------

    @abstractmethod
    def invoke(self, prompt: str) -> None:
        """Run the agent to completion, reporting spend via :meth:`note_spend`."""

    @abstractmethod
    def changed_files(self) -> list[str]:
        """Absolute paths the agent reports having written, best effort."""

    def cleanup(self) -> None:
        """Release agent resources. Called after the final diff is taken."""

    # -- run ----------------------------------------------------------------

    def run(self) -> tuple[str | None, bool]:
        """Run the agent and return ``(diff, budget_exhausted)``.

        The diff is None if the agent never started.
        """
        self.prepare()
        self.repo = self.start_baseline()
        try:
            self.invoke(self.prompt())
        except AgentUnavailable as exc:
            print(f"{self.name}: {exc}", flush=True)
            return None, False
        except Exception as exc:  # noqa: BLE001 - a crashed agent still has a diff
            print(f"{self.name} run ended with {type(exc).__name__}: {exc}", flush=True)
        finally:
            self.stop_commands()
        try:
            return self.final_diff(), self.budget_exhausted
        finally:
            self.cleanup()

    def prompt(self) -> str:
        """The task prompt, plus the no-browser note when it is enabled."""
        text = PROMPT.format(project=self.project, repo_folder=self.repo_folder,
                             sanitizer_report=self.sanitizer_report)
        if NO_BROWSER_FLAG:
            text += NO_BROWSER_PROMPT
        return text

    # -- the agent's environment --------------------------------------------

    def prepare(self) -> None:
        """Point command forwarding at this task and show the shared folders to the agent.

        The files there keep the owners the task image and root's commands
        give them; the agent's view shows them all as its own. Mounting needs a
        privilege this container does not have, so Docker runs that one step
        with it.
        """
        task_container = os.environ.get("PATCHBENCH_TASK_CONTAINER")
        if task_container:
            Path(TASK_CONTAINER_FILE).write_text(task_container)
        subprocess.run([DOCKER, "exec", "--privileged", os.environ["PATCHBENCH_AGENT_CONTAINER"],
                        VIEW, AGENT_USER, *SHARED_ROOTS], check=True)

    def agent_env(self, **extra: str) -> dict[str, str]:
        """The environment to start the agent program with.

        Its ``PATH`` is the one the task container's commands start with, as
        if the agent ran on the task's machine: an agent may write its own
        ``PATH`` into the commands it runs (Claude Code does).

        Its names and its ``PATH`` are recorded for agent/shell, which passes a
        command only what the agent adds on top of them. The API keys are left
        out of that record, so a command sees them as it would on a machine
        where the agent was started with them.
        """
        env = {"HOME": AGENT_HOME, "PATH": self.task_path(), "LANG": "C.UTF-8", **extra}
        names = (set(env) | set(os.environ)) - set(API_KEY_NAMES)
        Path(BASE_ENV_FILE).write_text("\n".join(sorted(names)))
        Path(BASE_PATH_FILE).write_text(env["PATH"])
        return env

    @staticmethod
    def task_path() -> str:
        """The ``PATH`` a command in the task container starts with."""
        task = Path(TASK_CONTAINER_FILE).read_text().strip()
        return subprocess.run([DOCKER, "exec", task, "printenv", "PATH"], capture_output=True,
                              text=True, check=True).stdout.strip()

    @staticmethod
    def as_agent() -> dict:
        """Keyword arguments that start a subprocess as the agent's user."""
        user = pwd.getpwnam(AGENT_USER)
        return {"user": user.pw_uid, "group": user.pw_gid, "extra_groups": []}

    @staticmethod
    def on_disk(path: str | Path) -> str:
        """Where root here writes ``path``, a path in the shared folders."""
        return DISK + os.path.abspath(path)

    @staticmethod
    def file_allowed(path: str | None, cwd: str) -> bool:
        """Whether a file tool may touch ``path``: only the shared folders."""
        path = path or cwd
        if path.startswith("~"):
            path = AGENT_HOME + path[1:]
        full = os.path.realpath(os.path.join(cwd, path))
        return any(full == root or full.startswith(root + "/") for root in SHARED_ROOTS)

    @staticmethod
    def stop_commands(grace: float = 15) -> None:
        """Stop every command the agent left running in the task container.

        Each runs under its own agent/forward process, which stops the command
        there when it is told to stop.
        """
        def forwarders() -> list[int]:
            pids = []
            for entry in Path("/proc").iterdir():
                try:
                    if entry.name.isdigit() and FORWARD in (entry / "cmdline").read_bytes().decode(errors="ignore"):
                        pids.append(int(entry.name))
                except OSError:
                    continue
            return pids

        for pid in forwarders():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.time() + grace
        while forwarders() and time.time() < deadline:
            time.sleep(0.5)

    # -- git ----------------------------------------------------------------

    def start_baseline(self) -> Repo:
        """Re-initialise the checkout so the diff is against a known baseline."""
        git_dir = Path(self.on_disk(self.repo_folder)) / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        repo = Repo.init(self.on_disk(self.repo_folder))
        repo.git.add(A=True)
        self.mask_id = self.commit(repo)
        return repo

    @staticmethod
    def commit(repo: Repo) -> str:
        msg = f"Auto-commit on {time.strftime('%Y-%m-%d %H:%M:%S')}"
        repo.git.commit("--allow-empty", "--no-verify", "-m", msg)
        return repo.head.commit.hexsha

    def diff_between(self, base_sha: str, head_sha: str) -> str:
        return self.repo.git.execute(["git", "diff", base_sha, head_sha],
                                     stdout_as_string=True,
                                     strip_newline_in_stdout=False)

    def diff_worktree(self, base_sha: str) -> str:
        """``base_sha`` against the working tree, so uncommitted edits count."""
        return self.repo.git.execute(["git", "diff", "--binary", base_sha, "--"],
                                     stdout_as_string=True,
                                     strip_newline_in_stdout=False)

    def stage(self, paths: list[str]) -> None:
        """Stage the agent's edits, skipping anything outside the checkout."""
        for path in paths:
            if not path.startswith(self.repo_folder + "/") or path.endswith(".md"):
                continue
            try:
                self.repo.git.add(self.on_disk(path))
            except Exception as exc:  # noqa: BLE001 - one bad path must not lose the rest
                print(f"Error adding {path}: {exc}", flush=True)

    def status_changed_files(self) -> list[str]:
        """C/C++ files git reports as modified, for when the agent reports none."""
        changed = []
        for line in self.repo.git.status("--porcelain").splitlines():
            if len(line) < 4:
                continue
            status, path = line[:2], line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if Path(path).suffix.lower() not in C_CPP_EXTENSIONS:
                continue
            if "M" in status and not any(c in status for c in "ADRC?"):
                changed.append(os.path.join(self.repo_folder, path))
        return sorted(set(changed))

    # -- budget -------------------------------------------------------------

    def note_spend(self, spend: float) -> bool:
        """Record spend, writing a snapshot per threshold crossed (if ``COST_STEP`` is set).

        Returns True once ``BUDGET_LIMIT`` is reached. Stopping is left to the
        caller, because each agent is interrupted differently.
        """
        print(f"[{self.name}] spend ${spend:.4f} / ${BUDGET_LIMIT:.2f}", flush=True)
        while (self._next_threshold < len(self._thresholds)
               and spend >= self._thresholds[self._next_threshold]):
            self.snapshot(self._thresholds[self._next_threshold])
            self._next_threshold += 1
        if spend >= BUDGET_LIMIT:
            self.budget_exhausted = True
        return self.budget_exhausted

    def snapshot(self, threshold: int) -> None:
        """Write the patch as it stands at a budget threshold."""
        self.stage(self.changed_files())
        self.commit(self.repo)
        path = f"{self.out_base}_{threshold}.diff"
        Path(path).write_text(self.diff_worktree(self.mask_id), errors="ignore")
        print(f"Snapshot at {threshold} dollars saved to {path}", flush=True)

    # -- final diff ---------------------------------------------------------

    def final_diff(self) -> str:
        """Stage everything the agent touched and diff it against the baseline."""
        changed = self.changed_files()
        if not changed:
            print(f"No files reported by {self.name}; falling back to git status.",
                  flush=True)
            changed = self.status_changed_files()
        if not changed:
            print("No files were changed by the agent.", flush=True)
        self.stage(changed)
        self.commit(self.repo)
        return self.diff_between(self.mask_id, "HEAD")


def main(harness_cls: type[AgentHarness]) -> None:
    """Parse the command line and run ``harness_cls``."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--task-id", dest="task_id")
    # Older generated scripts pass the task id under this name.
    parser.add_argument("--sanitizer_report", dest="task_id",
                        help=argparse.SUPPRESS)
    parser.add_argument("--repo-folder", required=True)
    parser.add_argument("--out-base", required=True)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--effort", choices=EFFORT_LEVELS, default=DEFAULT_EFFORT)
    args = parser.parse_args()

    if not args.task_id:
        parser.error("--task-id is required")

    harness = harness_cls(
        model_name=args.model_name,
        task_id=args.task_id,
        repo_folder=args.repo_folder,
        out_base=args.out_base,
        log_dir=args.log_dir or f"/logs/{harness_cls.name}",
        effort=args.effort,
    )
    diff, budget_exhausted = harness.run()
    if diff is not None:
        Path(f"{args.out_base}.diff").write_text(diff, errors="ignore")
    if budget_exhausted:
        print(f"[{harness_cls.name}] stopped on the ${BUDGET_LIMIT} budget", flush=True)
    hand_back(args.out_base, harness.log_dir)


def hand_back(out_base: str, log_dir: Path) -> None:
    """Give the patch, its snapshots and the logs to the host user."""
    uid, gid = os.environ.get("HOST_UID"), os.environ.get("HOST_GID")
    if not uid or not gid:
        return
    base = Path(out_base)
    for path in [*base.parent.glob(f"{base.name}*.diff"), log_dir]:
        subprocess.run(["chown", "-R", f"{uid}:{gid}", str(path)], check=False)
