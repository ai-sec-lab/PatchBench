"""Inference: run a coding agent against a task and collect the patch it produces."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config.constants import AGENT_INSTALL_COMMANDS
from ..paths import PATHS, Paths
from .utils import DockerScript, Job, ProcOutput, Stage, Task


class Inference(Stage):
    """Runs each agent inside the task's own container and collects its diff.

    The agent works in the real build environment so it can compile and test,
    and only the patch it leaves in ``/diff`` is carried forward.
    """

    stage = "infer"
    result_keys = ("patch",)
    timeout = 14400
    retries = 1

    #: Python the agent's toolchain is installed against, independent of the
    #: image's own interpreter.
    AGENT_PYTHON = "3.12"

    #: API keys forwarded from the host environment at run time. Their values
    #: are never written into the generated script.
    FORWARDED_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")

    #: Agents that cannot be installed inside the task image. Their harness runs
    #: on the host instead and drives the container from outside; the diff it
    #: leaves behind is identical either way.
    HOST_SIDE_AGENTS = {"claudecode"}

    def __init__(self, paths: Paths = PATHS, rerun: bool = False) -> None:
        super().__init__(paths)
        self.rerun = rerun

    # -- paths --------------------------------------------------------------

    def script_path(self, task: Task) -> Path:
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    def diff_path(self, task: Task) -> Path:
        """Where the harness is expected to leave this task's patch."""
        return self.paths.diff_dir(task.id) / task.diff_name

    def agent_log_dir(self, task: Task) -> Path:
        """The agent's own session logs, mounted as ``/.{agent}``."""
        return self.run_dir(task, "patch") / "agent"

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the script that runs this task's agent and collects its patch."""
        self.paths.diff_dir(task.id).mkdir(parents=True, exist_ok=True)
        self.agent_log_dir(task).mkdir(parents=True, exist_ok=True)

        if task.agent in self.HOST_SIDE_AGENTS:
            self.script_path(task).parent.mkdir(parents=True, exist_ok=True)
            self.script_path(task).write_text(self.host_script(task))
            return

        if task.agent not in AGENT_INSTALL_COMMANDS:
            raise ValueError(f"unsupported agent: {task.agent}")

        env: dict[str, str | None] = {"MAKEFLAGS": "-j8"}
        env.update({key: None for key in self.FORWARDED_KEYS})

        script = DockerScript(
            image=task.image,
            name=self.container_name(task),
            volumes=[
                f"{self.paths.harnesses}:/harnesses",
                # The harnesses import this by name from their working directory.
                f"{self.paths.root / 'patchbench' / 'config' / 'constants.py'}:/workdir/constants.py",
                f"{self.paths.diff_dir(task.id)}:/diff",
                f"{self.agent_log_dir(task)}:/.{task.agent}",
            ],
            env=env,
        )
        script.write(
            self.script_path(task),
            DockerScript.limit_nproc()
            + self.install_agent(task)
            + DockerScript.locate_repo(self.project_of(task))
            + self.run_harness(task),
        )

    def host_script(self, task: Task) -> str:
        """Script for an agent that runs on the host rather than in the image.

        The harness is handed the same ``--out-base`` as the container-side
        agents, so every downstream stage is unaffected by where it ran.
        """
        root = self.paths.root
        return (
            "#!/bin/bash\n"
            f"cd {root}\n"
            # constants.py is imported by name, matching the container-side mount.
            f"PYTHONPATH={root / 'patchbench' / 'config'} \\\n"
            f"  uv run --extra {task.agent} harnesses/{task.agent}_harness.py \\\n"
            f"    --model-name {task.model_name} \\\n"
            f'    --sanitizer_report "{task.id}" \\\n'
            f"    --project {self.project_of(task)} \\\n"
            f"    --image {task.image} \\\n"
            f"    --container {self.container_name(task)} \\\n"
            f"    --out-base {self.paths.diff_dir(task.id) / task.slug} \\\n"
            f"    --workdir {self.paths.work_dir(task.id, task.slug)} \\\n"
            f"    --log-dir {self.agent_log_dir(task)}\n"
        )

    def install_agent(self, task: Task) -> str:
        """Provision uv and the agent's own toolchain inside the container."""
        return (
            # The constants mount already creates /workdir, so this must not
            # be a `mkdir && cd` chain -- the failed mkdir would skip the cd.
            "mkdir -p /workdir\n"
            "cd /workdir\n"
            "apt install -y curl\n"
            "curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "cp -r /harnesses/* /workdir\n"
            ". /root/.local/bin/env\n"
            f"uv python install {self.AGENT_PYTHON}\n"
            f"uv venv --python {self.AGENT_PYTHON}\n"
            + AGENT_INSTALL_COMMANDS[task.agent].replace("\\$", "$").replace('\\"', '"')
        )

    def run_harness(self, task: Task) -> str:
        """Invoke the agent's harness, then hand the outputs back to the host user."""
        return (
            "cd /workdir\n"
            f"uv run {task.agent}_harness.py"
            f" --model-name {task.model_name}"
            # The host owns the naming scheme, so the harness is told where to
            # write rather than rebuilding the path from its own arguments.
            f" --out-base /diff/{task.slug}"
            ' --repo-folder $GIT_DIR'
            f' --sanitizer_report "{task.id}"\n'
            + DockerScript.chown_to_host(f"/.{task.agent}", "/diff")
        )

    # -- execution ----------------------------------------------------------

    def jobs_for(self, task: Task) -> list[Job]:
        """One job per task, skipped when a patch already exists and rerun is off."""
        script = self.script_path(task)
        if not script.is_file():
            return []
        if not self.rerun and self.diff_path(task).is_file():
            print(f"[infer] using existing patch for {task}")
            return []
        return [Job(task, "patch", ["/bin/bash", str(script)])]

    def run(self, tasks, rerun: bool, num_workers: int) -> Path:
        """Run inference, then report which tasks ended up with a patch.

        Unlike the evaluation stages, ``rerun`` here decides whether a task with
        an existing patch is asked again rather than whether containers run.
        """
        self.rerun = rerun
        jobs = [job for task in tasks for job in self.jobs_for(task)]
        print(f"[infer] running {len(jobs)} of {len(tasks)} tasks")
        self.run_jobs(jobs, num_workers)

        results: dict[Task, dict[str, Any]] = {}
        for task in tasks:
            self._record_patch(results, task)
        return self.write_report(results, len(tasks))

    def _record_patch(self, results: dict, task: Task) -> None:
        diff = self.diff_path(task)
        size = diff.stat().st_size if diff.is_file() else 0
        results[task] = {"patch": {"produced": size > 0, "bytes": size}}

    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """Unused: the verdict comes from the patch on disk, not the container log."""
        return {"produced": self.diff_path(task).is_file()}
