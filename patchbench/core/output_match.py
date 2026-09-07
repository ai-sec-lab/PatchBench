"""Functional verification: does the patched build still produce correct output?"""

from __future__ import annotations

import csv
import json
import os
import shlex
from functools import cached_property
from pathlib import Path
from typing import Any

from .utils import (CORPUS_PARALLELISM, DockerScript, Job, ProcOutput, Stage,
                    Task, engine_options)


class OutputMatch(Stage):
    """Replays known-good corpus inputs and diffs the output against a reference.

    An instrumented fuzz target is transplanted into the tree before the build so
    each replay writes its result to a fixed path, which is then compared
    byte-for-byte with the recorded reference output.
    """

    stage = "verify"
    result_keys = ("verify",)
    timeout = 6000
    retries = 1

    #: Where the fuzz target writes its result when the CSV records no other path.
    DEFAULT_OUTPUT_PATH = "/tmp/output"

    # -- inputs -------------------------------------------------------------

    @cached_property
    def fuzz_targets(self) -> dict[str, dict[str, str]]:
        """Per-task fuzz-target source, binary and output paths inside the image."""
        info: dict[str, dict[str, str]] = {}
        with self.paths.fuzz_targets.open() as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if len(row) < 4:
                    continue
                output = row[4].strip() if len(row) >= 5 and row[4].strip() else self.DEFAULT_OUTPUT_PATH
                info[row[0].strip()] = {
                    "project_name": row[1].strip(),
                    "src_path": row[2].strip(),
                    "org_path": row[3].strip(),
                    "output_path": output,
                }
        return info

    @cached_property
    def corpus_valid(self) -> dict[str, list[str]]:
        """Per-task corpus inputs that have a recorded reference output."""
        return json.loads(self.paths.corpus_valid.read_text())

    def instrumented_target(self, task_id: str) -> Path | None:
        """The instrumented fuzz-target source for a task, if one was generated."""
        directory = self.paths.instrumented_targets / str(task_id)
        if not directory.is_dir():
            return None
        return next((p for p in sorted(directory.iterdir()) if p.is_file()), None)

    def skip_reason(self, task: Task) -> str | None:
        """Why this task cannot be verified, or None if it can."""
        if task.id not in self.fuzz_targets:
            return f"not in {self.paths.fuzz_targets.name}"
        if task.id not in self.corpus_valid:
            return f"not in {self.paths.corpus_valid.name}"
        if task.id not in self.metadata:
            return f"not in {self.paths.metadata.name}"
        if self.instrumented_target(task.id) is None:
            return f"no instrumented target under {self.paths.instrumented_targets / task.id}"
        return None

    # -- paths --------------------------------------------------------------

    def script_path(self, task: Task) -> Path:
        return self.paths.script_dir(self.stage, task.id) / f"{task.slug}.sh"

    def outputs_dir(self, task: Task) -> Path:
        """Where this task's replayed outputs are collected for comparison."""
        return self.run_dir(task, "verify") / "outputs"

    # -- setup --------------------------------------------------------------

    def build_scripts(self, task: Task) -> None:
        """Write the replay script, its per-input runner, and the input list."""
        reason = self.skip_reason(task)
        if reason:
            print(f"[{self.stage}] skipping {task.id}: {reason}")
            return

        info = self.fuzz_targets[task.id]
        asan_options, target_args = engine_options(self.metadata[task.id]["fuzzer"])

        script_dir = self.paths.script_dir(self.stage, task.id)
        script_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir(task).mkdir(parents=True, exist_ok=True)

        valid_list = script_dir / f"{task.slug}_valid_inputs.txt"
        valid_list.write_text("".join(f"{n}\n" for n in self.corpus_valid[task.id]))

        run_one = script_dir / f"{task.slug}_run_one.sh"
        run_one.write_text(self.run_one_body(asan_options, target_args))

        target = self.instrumented_target(task.id)
        script = DockerScript(
            image=task.image,
            name=self.container_name(task),
            volumes=[
                f"{self.paths.diff_dir(task.id)}:/patches",
                f"{self.paths.corpus / task.id / 'C2'}:/corpus",
                f"{self.paths.instrumented_targets / task.id}:/instrumented_target",
                f"{valid_list}:/valid_inputs.txt:ro",
                f"{run_one}:/run_one.sh:ro",
                f"{self.outputs_dir(task)}:/verify_out",
            ],
            env={"MAKEFLAGS": "-j8"},
            # The per-replay mount namespace needs more than --cap-add SYS_ADMIN.
            privileged=True,
        )
        script.write(
            self.script_path(task),
            DockerScript.limit_nproc()
            + DockerScript.locate_repo(info["project_name"])
            + DockerScript.apply_patch(task.diff_name)
            + self.transplant_target(info["src_path"], target.name)
            + DockerScript.compile_with_retry()
            + self.replay_body(info["org_path"], info["output_path"]),
        )

    @staticmethod
    def transplant_target(src_path: str, target_filename: str) -> str:
        """Overwrite the fuzz-target source with the instrumented copy before building."""
        return f"""\
SRC_DST={shlex.quote(src_path)}
TARGET_SRC=/instrumented_target/{target_filename}
if [ -f "$TARGET_SRC" ]; then
  mkdir -p "$(dirname "$SRC_DST")"
  cp "$TARGET_SRC" "$SRC_DST"
  echo "Copied instrumented target to $SRC_DST"
else
  echo "WARNING: instrumented target not found at $TARGET_SRC"
fi
"""

    @staticmethod
    def run_one_body(asan_options: str, target_args: str) -> str:
        """The ``/run_one.sh`` replay script, kept in its own file for legibility.

        The output path is baked into the fuzz target at compile time, so each
        replay is isolated by binding a private directory over it.
        """
        return f"""\
#!/bin/sh
# Replay a single corpus input. Invoked as: run_one.sh <input-name> <index>
# Env supplied by the caller: WORK, ORG_BIN, OUTPUT_SRC, OUTPUT_DIR, USE_NS
name="$1"
idx="$2"
input="/corpus/$name"
log="$WORK/$idx.log"
slot="$WORK/slot.$idx"
: > "$log"

if [ ! -f "$input" ]; then
    printf 'MISSING_INPUT %s\\n' "$name" >> "$log"
    touch "$WORK/FAILED"
    exit 0
fi

mkdir -p "$slot"
export NAME="$name" INPUT="$input" LOG="$log" SLOT="$slot"

# Everything this script keeps -- logs, the FAILED sentinel, /verify_out --
# lives outside $OUTPUT_DIR so it survives the bind mount.
replay='
  if [ "$USE_NS" = "1" ]; then
    mount --bind "$SLOT" "$OUTPUT_DIR" || exit 97
  fi
  rm -f "$OUTPUT_SRC"
  ASAN_OPTIONS={asan_options} \\
  LSAN_OPTIONS=detect_leaks=0 \\
  "$ORG_BIN"{target_args} "$INPUT" </dev/null >>"$LOG" 2>&1
  ec=$?
  if [ -f "$OUTPUT_SRC" ]; then
    cp "$OUTPUT_SRC" "/verify_out/$NAME.output"
  else
    printf "MISSING_OUTPUT %s (exit=%s)\\n" "$NAME" "$ec" >> "$LOG"
    touch "$WORK/FAILED"
  fi
'

if [ "$USE_NS" = "1" ]; then
    unshare -m /bin/sh -c "$replay"
    if [ $? -eq 97 ]; then
        printf 'NAMESPACE_FAILED %s\\n' "$name" >> "$log"
        touch "$WORK/FAILED"
    fi
else
    /bin/sh -c "$replay"
fi
"""

    @classmethod
    def replay_body(cls, org_path: str, output_path: str) -> str:
        """Bash that replays every listed input, up to MAXJOBS at a time.

        One probe decides the mode for the whole run: without a usable mount
        namespace, parallel replays would overwrite each other's output.
        """
        output_dir = os.path.dirname(output_path) or "/"
        return f"""\
mkdir -p /verify_out
export ORG_BIN={shlex.quote(org_path)}
export OUTPUT_SRC={shlex.quote(output_path)}
export OUTPUT_DIR={shlex.quote(output_dir)}
export WORK=/verify_work
rm -rf "$WORK"
mkdir -p "$WORK"
MAXJOBS={CORPUS_PARALLELISM}
if unshare -m /bin/true 2>/dev/null; then
  export USE_NS=1
else
  export USE_NS=0
  MAXJOBS=1
  echo "WARNING: mount namespaces unavailable (needs a privileged container); replaying sequentially"
fi
echo "Replaying valid inputs (parallel $MAXJOBS, USE_NS=$USE_NS)"
IDX=0
while IFS= read -r name || [ -n "$name" ]; do
  [ -z "$name" ] && continue
  IDX=$((IDX+1))
  /bin/sh /run_one.sh "$name" "$IDX" &
  while [ "$(jobs -rp | wc -l)" -ge "$MAXJOBS" ]; do wait -n; done
done < /valid_inputs.txt
wait
cat $WORK/*.log </dev/null 2>/dev/null
if [ -f "$WORK/FAILED" ]; then
  echo "At least one input did not produce an output file"
fi
rm -rf "$WORK"
""" + DockerScript.chown_to_host("/verify_out")

    def jobs_for(self, task: Task) -> list[Job]:
        script = self.script_path(task)
        return [Job(task, "verify", ["/bin/bash", str(script)])] if script.is_file() else []

    # -- verdicts -----------------------------------------------------------

    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """1 when every valid input reproduced its reference output byte-for-byte."""
        if task.id not in self.corpus_valid:
            return 0
        produced = self.outputs_dir(task)
        expected = self.paths.corpus_outputs / task.id

        for name in self.corpus_valid[task.id]:
            got, want = produced / f"{name}.output", expected / f"{name}.output"
            if not got.is_file() or not want.is_file():
                return 0
            if got.stat().st_size != want.stat().st_size:
                return 0
            if got.read_bytes() != want.read_bytes():
                return 0
        return 1
