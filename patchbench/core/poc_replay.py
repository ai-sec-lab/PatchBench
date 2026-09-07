"""Replays the vulnerability's proof-of-concept against the patched build."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .utils import (DockerScript, Job, ParseError, ProcOutput, Stage, Task,
                    extract_sanitizer_block)


class PocReplay(Stage):
    """Rebuilds the patched tree and replays the input that triggered the CVE.

    A sanitizer report means the patch did not fix the vulnerability.
    """

    stage = "poc"
    result_keys = ("poc",)
    timeout = 6000
    retries = 5

    def script_path(self, task: Task) -> Path:
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the container script that rebuilds and replays the PoC."""
        script = DockerScript(
            image=task.image,
            name=self.container_name(task),
            volumes=[f"{self.paths.diff_dir(task.id)}:/patches"],
            env={"MAKEFLAGS": "-j8"},
        )
        script.write(
            self.script_path(task),
            DockerScript.limit_nproc()
            + DockerScript.locate_repo(self.project_of(task))
            + DockerScript.apply_patch(task.diff_name)
            + DockerScript.compile_with_retry()
            + "vulpatch run\n",
        )

    def jobs_for(self, task: Task) -> list[Job]:
        script = self.script_path(task)
        return [Job(task, self.stage, ["/bin/bash", str(script)])] if script.is_file() else []

    # -- verdicts -----------------------------------------------------------

    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """Decide whether the PoC still crashes the patched build."""
        stdout = proc.stdout.decode(errors="ignore")
        stderr = proc.stderr.decode(errors="ignore")

        if proc.returncode == 0:
            return "pass"

        if extract_sanitizer_block(stderr):
            return "crash"

        # A non-zero exit without a sanitizer report is not a security result:
        # the fuzz target refused to run, or the build never produced one.
        no_crash = (
            r"NOTE: fuzzing was not performed",
            r"Usage for fuzzing: honggfuzz",
            r"This binary is built for AFL-fuzz\.",
        )
        if any(re.search(p, stderr) for p in no_crash) or \
           re.search(r"Execution successful\.", stdout) or \
           re.search(r"make.*: Leaving directory .*$", stdout):
            raise ParseError(f"no crash detected with non zero return code ({proc.returncode})")

        if re.search(r"BUILD FAILED", stdout):
            raise ParseError(f"compile error ({proc.returncode})")

        raise ParseError(f"no matching regex case ({proc.returncode})")
