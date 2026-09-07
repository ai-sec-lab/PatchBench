"""Replays the recorded corpus against the patched build, looking for crashes.

No inputs are generated or mutated: the corpus is fixed, so this measures
whether the patch introduced a crash rather than searching for new ones.
"""

from __future__ import annotations

import re
from typing import Any

from .utils import (CORPUS_PARALLELISM, DockerScript, Job, ProcOutput, Stage,
                    Task, classify_crash, engine_options)


class CorpusReplay(Stage):
    """Replays both corpus buckets against the patched build in one container.

    C1 (seeds around the vulnerability) and C2 (the wider corpus) share a
    container so the expensive rebuild happens once, and are split back apart
    from the output markers.
    """

    stage = "replay"
    result_keys = ("C1", "C2")
    timeout = 7200
    retries = 5

    def script_path(self, task: Task):
        """Location of the generated replay script for one task."""
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the single container script that replays both buckets."""
        meta = self.metadata[task.id]
        asan_options, target_args = engine_options(meta["fuzzer"])
        run_command = (f'ASAN_OPTIONS={asan_options} LSAN_OPTIONS=detect_leaks=0 '
                       f'$FUZZ_TARGET{target_args} "$input"')
        fuzz_target = meta["command"].split()[0]
        script = DockerScript(
            image=task.image,
            name=self.container_name(task),
            volumes=[
                f"{self.paths.diff_dir(task.id)}:/patches",
                f"{self.paths.corpus / task.id}:/corpus",
            ],
            env={"MAKEFLAGS": "-j8"},
        )
        script.write(
            self.script_path(task),
            DockerScript.limit_nproc()
            + DockerScript.locate_repo(meta["project"])
            + DockerScript.apply_patch(task.diff_name)
            + DockerScript.compile_with_retry()
            + self.replay_body(fuzz_target, run_command),
        )

    #: Markers bracketing each bucket, so ``split`` can separate them again.
    BEGIN_MARKER = "###BUCKET_BEGIN $BUCKET###"
    END_MARKER = "###BUCKET_END $BUCKET rc=$RC###"

    @classmethod
    def replay_body(cls, fuzz_target: str, run_command: str) -> str:
        """Bash that replays each bucket, bracketed by markers ``split`` reads.

        A failing input is re-run verbosely into its own file and those are
        concatenated afterwards, so concurrent sanitizer reports cannot interleave.
        """
        return f"""\
FUZZ_TARGET="{fuzz_target}"
MAXJOBS={CORPUS_PARALLELISM}
shopt -s nullglob
run_bucket() {{
  BUCKET=$1
  SUBDIR="/corpus/$BUCKET"
  CORPUS_FILES=($SUBDIR/*)
  echo "{cls.BEGIN_MARKER}"
  echo "{cls.BEGIN_MARKER}" >&2
  RC=0
  if [ ${{#CORPUS_FILES[@]}} -eq 0 ]; then
    echo "No corpus inputs found under $SUBDIR"
    RC=1
  else
    echo "Running ${{#CORPUS_FILES[@]}} inputs from $SUBDIR with fuzz target: $FUZZ_TARGET (parallel $MAXJOBS)"
    WORK=$(mktemp -d)
    IDX=0
    for input in "${{CORPUS_FILES[@]}}"; do
      IDX=$((IDX+1))
      (
        {run_command} >/dev/null 2>/dev/null
        EXIT_CODE=$?
        if [ $EXIT_CODE -ne 0 ]; then
          {{
            echo "Re-running failing input: $input (exit code: $EXIT_CODE)"
            {run_command} 2>&1
          }} > "$WORK/$IDX.log"
          touch "$WORK/FAILED"
        fi
      ) &
      while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do wait -n; done
    done
    wait
    cat $WORK/*.log >&2 </dev/null 2>/dev/null
    if [ -f "$WORK/FAILED" ]; then RC=1; fi
    rm -rf "$WORK"
  fi
  echo "{cls.END_MARKER}"
  echo "{cls.END_MARKER}" >&2
  return $RC
}}
run_bucket C1
C1_RC=$?
run_bucket C2
C2_RC=$?
if [ $C1_RC -ne 0 ] || [ $C2_RC -ne 0 ]; then
  exit 1
fi
"""

    def jobs_for(self, task: Task) -> list[Job]:
        script = self.script_path(task)
        return [Job(task, "C1+C2", ["/bin/bash", str(script)])] if script.is_file() else []

    # -- verdicts -----------------------------------------------------------

    def split(self, job: Job, proc: ProcOutput) -> dict[str, ProcOutput]:
        """Carve one container run back into a result per corpus bucket."""
        parts: dict[str, ProcOutput] = {}
        for bucket in self.result_keys:
            out, out_rc = self._section(proc.stdout, bucket)
            err, err_rc = self._section(proc.stderr, bucket)
            if out is None and err is None:
                # The run died before this bucket -- a compile failure or an
                # outer timeout. Attribute the whole run to it.
                parts[bucket] = ProcOutput(proc.stdout, proc.stderr, proc.returncode)
            else:
                rc = out_rc if out_rc is not None else err_rc
                parts[bucket] = ProcOutput(out or b"", err or b"", rc)
        return parts

    @staticmethod
    def _section(stream: bytes, bucket: str) -> tuple[bytes | None, int | None]:
        """Return one bucket's slice of a merged stream, or (None, None)."""
        name = bucket.encode()
        begin = re.search(rb"^###BUCKET_BEGIN " + name + rb"###$", stream, re.M)
        end = re.search(rb"^###BUCKET_END " + name + rb" rc=(-?\d+)###$", stream, re.M)
        if not begin or not end or end.start() < begin.end():
            return None, None
        return stream[begin.end():end.start()].strip(b"\n"), int(end.group(1))

    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """A bucket passes when no input in it produced a sanitizer report."""
        return classify_crash(proc)
