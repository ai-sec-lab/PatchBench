"""Inference: run a coding agent against a task and collect the patch it produces.

Every agent runs the same way, in two containers:

* the **task container**, from the task image, where every command the agent
  runs is executed -- the OSS-Fuzz toolchain, the PoC and ``vulpatch`` included;
* the **agent container**, from ``agent/Dockerfile`` with only this task's
  agent installed, where the agent program and its harness run. Each shell in
  that image forwards its command to the task container. The few files of the
  agent's own that those commands rely on (``AGENT_FILES_IN_TASK``) are mounted
  into the task container read-only.

``/src``, ``/out``, ``/tmp`` and ``/root`` are copied out of the task image and
mounted at the same paths in both, so a file tool and a shell command see the
same files. The prompt is the same for every agent, and only the patch the
harness leaves in ``/diff`` is carried forward.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from ..config.constants import AGENT_API_KEYS, DEFAULT_EFFORT, MODEL_API_KEYS, MODELS
from ..paths import PATHS, Paths
from .utils import Job, Stage, Task


class Inference(Stage):
    """Runs an agent against one task and records the diff it produced."""

    stage = "infer"
    result_keys = ("patch",)
    timeout = 28800
    retries = 3
    live_output = True

    #: Image an agent lives in, one per agent, all built from
    #: ``agent/Dockerfile`` with ``--build-arg AGENT=<name>``. Built on first use
    #: (see :meth:`ensure_agent_image`); override to use images tagged some
    #: other way.
    AGENT_IMAGE_TEMPLATE = os.environ.get("PATCHBENCH_AGENT_IMAGE_TEMPLATE",
                                          "patchbench/agent-{agent}:latest")
    #: Image label holding a fingerprint of the files the image was built from.
    SOURCE_LABEL = "org.patchbench.source"

    #: Copied out of the task image and mounted at the same path in both
    #: containers; ``/root`` is also the agent's home.
    SHARED_DIRS = ("/src", "/out", "/tmp", "/root")

    #: Files of an agent's image that its commands need in the task container,
    #: mounted there read-only straight from the image. Codex puts
    #: ``apply_patch`` and ``applypatch`` on its commands' PATH as links to its
    #: own binary, and its package's ``codex-path`` (with ``rg``) in front of
    #: that PATH; agent/forward carries both folders over, and these are what
    #: they hold. Claude Code's commands run ``rg``, ``grep`` and ``find``
    #: from its own program, named by CLAUDE_CODE_EXECPATH, which agent/forward
    #: passes on only where that path exists. The path follows the agent
    #: image's Python (AGENT_PYTHON in agent/Dockerfile).
    AGENT_FILES_IN_TASK = {
        "codex": ("/opt/codex/bin/codex", "/opt/codex/codex-path"),
        "claudecode": ("/opt/agent/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude",),
    }

    def __init__(self, paths: Paths = PATHS, rerun: bool = False,
                 effort: str = DEFAULT_EFFORT) -> None:
        super().__init__(paths)
        self.rerun = rerun
        self.effort = effort

    # -- paths --------------------------------------------------------------

    def script_path(self, task: Task) -> Path:
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    def diff_path(self, task: Task) -> Path:
        """Where the harness is expected to leave this task's patch."""
        return self.paths.diff_dir(task.id) / task.diff_name

    def agent_log_dir(self, task: Task) -> Path:
        """The agent's own session logs."""
        return self.run_dir(task, "patch") / "agent"

    def work_dir(self, task: Task) -> Path:
        """Host-side home for the folders copied out of the task image."""
        return self.paths.work_dir(task.id, task.slug)

    def harness_path(self, task: Task) -> Path:
        return self.paths.harnesses / f"{task.agent}_harness.py"

    def agent_image(self, task: Task) -> str:
        return self.AGENT_IMAGE_TEMPLATE.format(agent=task.agent)

    def task_container(self, task: Task) -> str:
        return f"{self.container_name(task)}_task"

    def agent_container(self, task: Task) -> str:
        return f"{self.container_name(task)}_agent"

    def containers_of(self, task: Task) -> list[str]:
        return [self.task_container(task), self.agent_container(task)]

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the script that runs this task's agent and collects its patch."""
        # Any agent with a harness is runnable; its image is built from the
        # same Dockerfile, so there is no list of supported agents to keep.
        if not self.harness_path(task).is_file():
            raise ValueError(f"no harness for agent {task.agent!r}: "
                             f"expected {self.harness_path(task)}")

        self.paths.diff_dir(task.id).mkdir(parents=True, exist_ok=True)
        self.agent_log_dir(task).mkdir(parents=True, exist_ok=True)
        self.script_path(task).parent.mkdir(parents=True, exist_ok=True)
        self.script_path(task).write_text(self.render(task))

    def render(self, task: Task) -> str:
        """The whole run: copy the shared folders, start both containers, collect."""
        project = self.project_of(task)
        work = self.work_dir(task)
        return "".join([
            "#!/bin/bash\n",
            "# Generated by patchbench; see patchbench/core/inference.py.\n",
            "set -uo pipefail\n",
            # Resolved on the host so the container can hand its writes back.
            "export HOST_UID=$(id -u) HOST_GID=$(id -g)\n",
            f"TASK_IMAGE={task.image}\n",
            f"AGENT_IMAGE={self.agent_image(task)}\n",
            f"TASK_CONTAINER={self.task_container(task)}\n",
            f"AGENT_CONTAINER={self.agent_container(task)}\n",
            f"WORK={work}\n",
            f"PROJECT={project}\n",
            "\n",
            self._extract_shared(),
            self._start_task_container(task),
            self._run_agent(task),
            self._collect(),
        ])

    def _mounts(self) -> str:
        """The shared folders, mounted at the same path in either container."""
        return "".join(f'  -v "$WORK{d}:{d}" \\\n' for d in self.SHARED_DIRS)

    def _extract_shared(self) -> str:
        """Copy the shared folders out of the task image and find the checkout."""
        return (
            # The shared folders hold files of root and the image's other owners
            # during the run, so on any exit -- a failed run included -- they all
            # go to the host user from inside that container before it is removed.
            "cleanup() {\n"
            '  docker exec "$TASK_CONTAINER" chown -R "$HOST_UID:$HOST_GID" '
            f'{" ".join(self.SHARED_DIRS)} >/dev/null 2>&1 || true\n'
            '  docker rm -f "$TASK_CONTAINER" "$AGENT_CONTAINER" >/dev/null 2>&1 || true\n'
            "}\n"
            # The shared folders are only needed while the run lasts: by its end
            # the patch is in /diff and the agent's logs in its log directory.
            # Files the host user cannot delete (a run killed before cleanup
            # could hand them back) are removed from inside a throwaway
            # container. Guarded because this is the one destructive step in the
            # script; it returns rather than exits, so the exit trap keeps the
            # agent's status.
            "clear_work() {\n"
            '  case "$WORK" in\n'
            '    */out/work/*) ;;\n'
            '    *) echo "refusing to clear $WORK" >&2; return 1 ;;\n'
            "  esac\n"
            '  rm -rf "$WORK" 2>/dev/null || {\n'
            '    docker run --rm -v "$WORK:/work" --entrypoint /bin/rm "$TASK_IMAGE" '
            f'-rf {" ".join("/work" + d for d in self.SHARED_DIRS)} >/dev/null 2>&1\n'
            '    rm -rf "$WORK"; }\n'
            '  rmdir "${WORK%/*}" 2>/dev/null || true\n'
            "}\n"
            "trap 'cleanup; clear_work' EXIT\n"
            "cleanup\n"
            # A previous run may have been killed before its exit trap ran.
            "clear_work || exit 1\n"
            'mkdir -p "$WORK"\n'
            'REPO=$(docker run --rm --entrypoint /bin/sh "$TASK_IMAGE" -c '
            "\"find /src -maxdepth 3 -type d -iname '$PROJECT' | head -n 1\")\n"
            'if [ -z "$REPO" ]; then echo "no checkout named $PROJECT under /src" >&2; exit 1; fi\n'
            # Copied by root inside the image with owners and modes kept, so the
            # task container sees what the image has; the agent sees them all
            # as its own (agent/view). `docker cp` unpacks as the host user, so
            # it stops at the first read-only folder it creates, such as Go's
            # module cache.
            'docker run --rm -v "$WORK:/work" --entrypoint /bin/sh "$TASK_IMAGE" -c '
            f'"cp -a {" ".join(self.SHARED_DIRS)} /work/" '
            "|| exit 1\n"
            "\n"
        )

    def _start_task_container(self, task: Task) -> str:
        """Run the task image with the shared folders mounted over its own."""
        agent_files = "".join(
            '  --mount type=image,source="$AGENT_IMAGE",'
            f'target={path},image-subpath={path.lstrip("/")} \\\n'
            for path in self.AGENT_FILES_IN_TASK.get(task.agent, ()))
        return (
            'docker run -dit --name "$TASK_CONTAINER" \\\n'
            '  --security-opt seccomp=unconfined \\\n'
            + self._mounts()
            + agent_files
            + '  "$TASK_IMAGE" bash >/dev/null || exit 1\n'
            "\n"
        )

    def _run_agent(self, task: Task) -> str:
        """Run the agent image against the same folders, in the foreground."""
        key = AGENT_API_KEYS.get(task.agent) or MODEL_API_KEYS.get(MODELS[task.model_name])
        if key is None:
            raise ValueError(f"no API key is known for {task.agent} with model {task.model_name}")
        return (
            'docker run --rm --name "$AGENT_CONTAINER" \\\n'
            '  --security-opt seccomp=unconfined \\\n'
            # Docker's AppArmor profile forbids the mounts agent/view makes,
            # even to a privileged process; the privilege itself is given to
            # that one step only (agent_base.AgentHarness.prepare). Its bindfs
            # views need the FUSE device.
            '  --security-opt apparmor=unconfined \\\n'
            '  --device /dev/fuse \\\n'
            # Only root here uses the socket: agent/forward, to start each of
            # the agent's commands in the task container, and the harness, to
            # set up the shared folders.
            '  -v /var/run/docker.sock:/var/run/docker.sock \\\n'
            + self._mounts()
            + f'  -v {self.paths.harnesses}:/harnesses:ro \\\n'
            # The harnesses import `constants` by name. It cannot be mounted
            # into /harnesses itself -- a file mount needs a mountpoint inside a
            # read-only mount -- so its directory goes on PYTHONPATH instead.
            f"  -v {self.paths.root / 'patchbench' / 'config'}:/patchbench-config:ro \\\n"
            '  -e PYTHONPATH=/patchbench-config \\\n'
            f'  -v {self.paths.diff_dir(task.id)}:/diff \\\n'
            f'  -v {self.agent_log_dir(task)}:/logs/{task.agent} \\\n'
            '  -e PATCHBENCH_TASK_CONTAINER="$TASK_CONTAINER" \\\n'
            '  -e PATCHBENCH_AGENT_CONTAINER="$AGENT_CONTAINER" \\\n'
            '  -e HOST_UID -e HOST_GID \\\n'
            # Only the key the agent reads, taken from the host environment at
            # run time; its value is never written into the script.
            f'  -e {key} \\\n'
            # The image's entrypoint is its Python; the harness gives its
            # outputs to HOST_UID itself.
            + '  "$AGENT_IMAGE" \\\n'
            f'  /harnesses/{task.agent}_harness.py \\\n'
            # The harness gets the full model name (`gpt-5` -> `gpt-5-2025-08-07`);
            # output names keep the name as given on the command line.
            f'    --model-name {MODELS[task.model_name]} \\\n'
            f'    --task-id {task.id} \\\n'
            '    --repo-folder "$REPO" \\\n'
            f'    --out-base /diff/{task.slug} \\\n'
            f'    --effort {self.effort} \\\n'
            f'    --log-dir /logs/{task.agent}\n'
            # Carried to the end, so the collect step's cleanup cannot mask a
            # failed agent behind a zero exit status.
            "AGENT_RC=$?\n"
            "\n"
        )

    def _collect(self) -> str:
        """End with the agent's status; the exit trap hands the folders back."""
        return 'exit "$AGENT_RC"\n'

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

    def agent_source(self, agent: str) -> str:
        """Fingerprint of the files an agent's image is built from."""
        root = self.paths.root / "agent"
        digest = hashlib.sha256()
        for path in ("Dockerfile", "shell", "forward", "view", f"install/{agent}.sh"):
            digest.update(path.encode() + b"\0" + (root / path).read_bytes())
        return digest.hexdigest()[:16]

    def ensure_agent_image(self, agent: str) -> None:
        """Build the agent's image unless an up-to-date one already exists.

        The harnesses are mounted at run time rather than baked in, so only a
        change to ``agent/`` itself calls for a rebuild.
        """
        image = self.AGENT_IMAGE_TEMPLATE.format(agent=agent)
        source = self.agent_source(agent)
        found = subprocess.run(
            ["docker", "image", "inspect", "--format",
             f'{{{{ index .Config.Labels "{self.SOURCE_LABEL}" }}}}', image],
            capture_output=True, text=True)
        if found.returncode == 0 and found.stdout.strip() == source:
            return
        print(f"[infer] building {image} from agent/ "
              f"({'out of date' if found.returncode == 0 else 'not built yet'})")
        subprocess.run(["docker", "build", "--build-arg", f"AGENT={agent}",
                        "--label", f"{self.SOURCE_LABEL}={source}",
                        "-t", image, str(self.paths.root / "agent")], check=True)

    def run(self, tasks, rerun: bool, num_workers: int) -> Path:
        """Run inference, then report which tasks ended up with a patch.

        Unlike the evaluation stages, ``rerun`` here decides whether a task with
        an existing patch is asked again rather than whether containers run.
        """
        self.rerun = rerun
        jobs = [job for task in tasks for job in self.jobs_for(task)]
        for agent in sorted({job.task.agent for job in jobs}):
            self.ensure_agent_image(agent)
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
