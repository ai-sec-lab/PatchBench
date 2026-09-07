"""Machinery shared by every benchmark stage.

The stages differ only in which containers they build and how they read a
verdict out of the result; everything around that lives here.
"""

from __future__ import annotations

import json
import pickle
import random
import re
import selectors
import subprocess
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from multiprocessing import Pool
from pathlib import Path
from typing import Any, ClassVar, Iterator, Sequence

from alive_progress import alive_bar

from ..paths import PATHS, Paths

class ParseError(Exception):
    """Raised when a container's output cannot be read as a verdict."""


# ---------------------------------------------------------------------------
# Task identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Task:
    """One evaluation unit: a task id under one agent configuration.

    The tuple is spelled three different ways on disk; those spellings are
    pinned here so callers never rebuild them by hand.
    """

    #: The container image every stage evaluates a task in, as published on
    #: Docker Hub. A locally tagged image of the same name is used as-is.
    IMAGE: ClassVar[str] = "b4drequest/vulpatch:{id}-vul"

    id: str
    agent: str
    model_name: str
    #: Free-form label separating otherwise identical runs. Left out of every
    #: generated name when empty, rather than leaving a trailing separator.
    tag: str = ""

    @classmethod
    def expand(
        cls,
        ids: Sequence[str],
        agents: Sequence[str],
        model_names: Sequence[str],
        tag: str = "",
    ) -> list["Task"]:
        """Every combination of the supplied axes, in a stable order."""
        return [
            cls(str(i), a, m, tag)
            for i, a, m in product(ids, agents, model_names)
        ]

    @property
    def image(self) -> str:
        """This task's evaluation image."""
        return self.IMAGE.format(id=self.id)

    @property
    def slug(self) -> str:
        """Identifies a run, in filenames, directories and container names."""
        parts = [self.agent, self.model_name]
        if self.tag:
            parts.append(self.tag)
        return "_".join(parts)

    @property
    def config(self) -> dict[str, str]:
        """The axes this run varies, recorded in the header of every report."""
        return {"agent": self.agent, "model": self.model_name, "tag": self.tag}

    @property
    def diff_name(self) -> str:
        """Filename of the patch this task's agent produced."""
        return f"{self.slug}.diff"

    def container_name(self, stage: str) -> str:
        """Container name for this task under one stage.

        The stage is part of the name so the stages can run concurrently
        against the same task without colliding.
        """
        return f"{self.id}_{self.slug}_{stage}"

    def __str__(self) -> str:
        return f"{self.id}_{self.slug}"


# ---------------------------------------------------------------------------
# Container script assembly
# ---------------------------------------------------------------------------


def quote_for_bash_c(script: str) -> str:
    """Escape a bash snippet for embedding in ``bash -c "..."``.

    The payload reaches the container as one double-quoted argument, so it must
    survive a round of expansion by the outer shell.
    """
    for char in ("\\", '"', "$", "`"):
        script = script.replace(char, "\\" + char)
    return script


def unquote_for_bash_c(script: str) -> str:
    """Undo one round of ``quote_for_bash_c`` escaping.

    The per-project commands in ``config.projects`` are stored already escaped
    for the container's outer shell, so they are unescaped before being handed
    to ``DockerScript``, which escapes every body uniformly.
    """
    out, i = [], 0
    while i < len(script):
        if script[i] == "\\" and i + 1 < len(script) and script[i + 1] in '\\"$`':
            out.append(script[i + 1])
            i += 2
        else:
            out.append(script[i])
            i += 1
    return "".join(out)


@dataclass
class DockerScript:
    """Builds the ``docker run`` wrapper scripts each stage executes.

    Body fragments are exposed individually because each stage composes them
    differently.
    """

    image: str
    name: str
    volumes: list[str] = field(default_factory=list)
    #: Environment for the container. A None value forwards the variable from
    #: the host at run time instead of writing its value into the script, so
    #: secrets never reach disk.
    env: dict[str, str | None] = field(default_factory=dict)
    cpus: int = 8
    privileged: bool = False

    # -- reusable body fragments --------------------------------------------

    @staticmethod
    def limit_nproc(jobs: int = 8) -> str:
        """Cap ``nproc`` so build systems honour the container's CPU quota."""
        return (
            "echo '#!/bin/sh' > /tmp/nproc\n"
            f"echo 'echo {jobs}' >> /tmp/nproc\n"
            "chmod +x /tmp/nproc\n"
            "export PATH=/tmp:$PATH\n"
        )

    @staticmethod
    def locate_repo(project_name: str) -> str:
        """Set ``GIT_DIR`` to the project checkout inside the image."""
        return (
            f"GIT_DIR=$(find /src -type d -iname '{project_name.lower()}' | head -n 1)\n"
            'git -C $GIT_DIR config --global user.email "anonymous@email.com"\n'
        )

    @staticmethod
    def apply_patch(diff_name: str, patch_dir: str = "/patches") -> str:
        """Apply the agent's diff, reporting but not failing on a bad patch so
        that an unpatched build still reaches the tests."""
        return (
            "ORIG_CWD=$PWD\n"
            "cd $GIT_DIR\n"
            f"if git apply {patch_dir}/{diff_name}; then\n"
            f'  echo "git apply succeeded: {diff_name}"\n'
            "fi\n"
            "cd $ORIG_CWD\n"
        )

    @staticmethod
    def chown_to_host(*paths: str) -> str:
        """Hand anything the container wrote back to whoever ran the script.

        The container runs as root, so its writes would otherwise be root-owned
        on the host. ``$HOST_UID``/``$HOST_GID`` are resolved by the host shell
        at run time rather than baked in when the script is generated.
        """
        return f"chown -R $HOST_UID:$HOST_GID {' '.join(paths)}\n"

    @staticmethod
    def compile_with_retry(attempts: int = 3) -> str:
        """Build the patched tree, retrying transient toolchain failures."""
        return (
            "ATTEMPTS=0\n"
            f"MAX_ATTEMPTS={attempts}\n"
            "SUCCESS=false\n"
            "while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do\n"
            "  ATTEMPTS=$((ATTEMPTS+1))\n"
            '  echo "Attempt #$ATTEMPTS: Running vulpatch compile..."\n'
            "  vulpatch compile\n"
            "  EXIT_CODE=$?\n"
            "  if [ $EXIT_CODE -eq 0 ]; then\n"
            '    echo "vulpatch compile succeeded on attempt #$ATTEMPTS"\n'
            "    SUCCESS=true\n"
            "    break\n"
            "  else\n"
            '    echo "vulpatch compile failed (exit code: $EXIT_CODE), retrying..."\n'
            "    sleep 2\n"
            "  fi\n"
            "done\n"
            'if [ "$SUCCESS" = false ]; then\n'
            '  echo "vulpatch compile failed after $MAX_ATTEMPTS attempts. Exiting."\n'
            "  exit 1\n"
            "fi\n"
        )

    # -- assembly -----------------------------------------------------------

    def render(self, body: str) -> str:
        """Wrap a bash body in the ``docker run`` invocation."""
        flags = [
            "--rm", "--init",
            f"--name {self.name}",
            f"--cpus={self.cpus}",
            "--security-opt seccomp=unconfined",
            "-e HOST_UID", "-e HOST_GID",
        ]
        if self.privileged:
            flags.append("--privileged")
        flags += [f"-e {k}" if v is None else f'-e {k}="{v}"'
                  for k, v in self.env.items()]
        flags += [f"-v {v}" for v in self.volumes]

        indented = "".join(f"  {line}\n" for line in body.splitlines())
        return (
            "#!/bin/bash\n"
            "# Resolved here, on the host, so the container can hand its writes\n"
            "# back to whoever runs this script.\n"
            "export HOST_UID=$(id -u) HOST_GID=$(id -g)\n"
            f"docker run {' '.join(flags)} {self.image} bash -c \"\n"
            f"{quote_for_bash_c(indented)}"
            '  "'
        )

    def write(self, path: Path, body: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(body))
        return path


# ---------------------------------------------------------------------------
# Container execution
# ---------------------------------------------------------------------------


@dataclass
class ProcOutput:
    """One container run's captured output, persisted so verdicts can later be
    re-derived without re-running the container."""

    stdout: bytes
    stderr: bytes
    returncode: int

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "stdout.txt").write_bytes(self.stdout)
        (directory / "stderr.txt").write_bytes(self.stderr)
        with (directory / "cache.pkl").open("wb") as f:
            pickle.dump(
                {
                    "stdout": self.stdout,
                    "stderr": self.stderr,
                    "returncode": self.returncode,
                    "timestamp": datetime.now().isoformat(),
                },
                f,
            )

    @classmethod
    def load(cls, directory: Path) -> "ProcOutput | None":
        cache = directory / "cache.pkl"
        if not cache.is_file():
            return None
        try:
            with cache.open("rb") as f:
                data = pickle.load(f)
        except (pickle.UnpicklingError, EOFError, AttributeError):
            return None
        return cls(data["stdout"], data["stderr"], data["returncode"])


class ScriptRunner:
    """Runs a generated script under a wall-clock and output-size budget.

    Output is streamed rather than buffered so a runaway build cannot exhaust
    memory or disk.
    """

    #: Per-stream cap. A passing run is orders of magnitude below this; a
    #: failing one stays recognisable after truncation.
    MAX_STREAM_BYTES = 50 * 1024 * 1024
    TRUNCATION_NOTICE = b"\n[output truncated]\n"

    def __init__(self, timeout: int = 3000, retries: int = 1,
                 retry_delay: int = 60) -> None:
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay

    def capture(self, proc: subprocess.Popen) -> tuple[bytes, bytes, bool, bool]:
        """Drain both streams until exit, timeout, or the size cap."""
        selector = selectors.DefaultSelector()
        chunks = {"stdout": [], "stderr": []}
        totals = {"stdout": 0, "stderr": 0}
        capped = {"stdout": False, "stderr": False}
        streams = {proc.stdout: "stdout", proc.stderr: "stderr"}

        for stream in streams:
            selector.register(stream, selectors.EVENT_READ)

        start = time.time()
        elapsed = 0.0
        while selector.get_map() and elapsed < self.timeout and not all(capped.values()):
            for key, _ in selector.select(timeout=1):
                data = key.fileobj.read1(4096)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                which = streams[key.fileobj]
                room = self.MAX_STREAM_BYTES - totals[which]
                if room > 0:
                    chunk = data[:room]
                    chunks[which].append(chunk)
                    totals[which] += len(chunk)
                capped[which] = totals[which] >= self.MAX_STREAM_BYTES
            elapsed = time.time() - start

        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

        for which in chunks:
            if capped[which]:
                chunks[which].append(self.TRUNCATION_NOTICE)

        return (
            b"".join(chunks["stdout"]),
            b"".join(chunks["stderr"]),
            elapsed >= self.timeout,
            all(capped.values()),
        )

    def run(self, cmd: Sequence[str], container_name: str, label: str = "") -> ProcOutput:
        """Execute one script, retrying only on upstream rate limiting."""
        stdout = stderr = b""
        returncode = -1

        for attempt in range(self.retries):
            proc = subprocess.Popen(
                list(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
            )
            stdout, stderr, timed_out, filled_up = self.capture(proc)
            returncode = proc.returncode

            if timed_out or filled_up:
                returncode = -1
                if timed_out:
                    print(f"Timeout: {label}", flush=True)
                    stderr = b"Timeout\n" + stderr
                if filled_up:
                    print(f"Truncated: {label}", flush=True)
                    stderr = b"Truncated\n" + stderr

            if b"429 Too Many Requests" not in stderr:
                break
            if attempt < self.retries - 1:
                delay = self.retry_delay * (2 ** attempt) + random.uniform(0, 10)
                print(f"Rate limit reached. Retrying in {delay:.2f}s...", flush=True)
                time.sleep(delay)
            else:
                print(f"Giving up on {label} after {self.retries} attempts", flush=True)

        # The container is started with --rm, but a run killed mid-flight can
        # leave it behind and block the next run on the same name.
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return ProcOutput(stdout, stderr, returncode)


# ---------------------------------------------------------------------------
# Fuzzing engines
# ---------------------------------------------------------------------------

#: Corpus inputs replayed concurrently inside one container, against its
#: ``--cpus`` quota. Each replay is a single-threaded process.
CORPUS_PARALLELISM = 8

#: Base ASan settings shared by every engine. Leak detection is off because a
#: leak is not the vulnerability under test.
_ASAN_BASE = "detect_leaks=0:detect_odr_violation=0:allocator_may_return_null=1"

#: Per-engine ``(ASAN_OPTIONS value, extra fuzz-target flags)``. libFuzzer's driver
#: caps RSS itself via ``-rss_limit_mb``, which also bounds single allocations;
#: the other engines' drivers have no such flag, so the cap comes from the ASan
#: runtime's own RSS monitor instead.
ENGINE_OPTIONS: dict[str, tuple[str, str]] = {
    "libfuzzer": (_ASAN_BASE, " -rss_limit_mb=8192"),
    "afl": (f"{_ASAN_BASE}:hard_rss_limit_mb=8192", ""),
}
ENGINE_OPTIONS["aflpp"] = ENGINE_OPTIONS["afl"]
ENGINE_OPTIONS["honggfuzz"] = ENGINE_OPTIONS["afl"]


def engine_options(engine: str) -> tuple[str, str]:
    """The ASan settings and fuzz-target flags for one fuzzing engine."""
    if engine not in ENGINE_OPTIONS:
        raise ValueError(f"unsupported fuzzer: {engine}")
    return ENGINE_OPTIONS[engine]


# ---------------------------------------------------------------------------
# Sanitizer output parsing
# ---------------------------------------------------------------------------

SANITIZER_START_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"^(\w+)Sanitizer:",
        r"^==\d+(?::\d+)?==(?:ERROR|WARNING): (\w+)Sanitizer:",
        r"runtime error:",
    )
)

SANITIZER_END_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"^==\d+==ABORTING",
        r"^Exiting",
        r"^SUMMARY: (\w+)Sanitizer",
    )
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def remove_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def extract_sanitizer_block(stderr: str) -> str:
    """Return the sanitizer report inside ``stderr``, or "" if there is none.

    Presence of a block -- not the exit code -- is what distinguishes a crash
    from an ordinary non-zero exit such as a build or fuzz-target failure.
    """
    lines = stderr.splitlines()
    if not lines:
        return ""

    start = next(
        (i for i, line in enumerate(lines)
         if any(p.search(line) for p in SANITIZER_START_PATTERNS)),
        None,
    )
    if start is None:
        return ""

    end = next(
        (i for i in range(start, len(lines))
         if any(p.search(lines[i]) for p in SANITIZER_END_PATTERNS)),
        len(lines) - 1,
    )
    return "\n".join(lines[start:end + 1]).strip()


def classify_crash(proc: ProcOutput) -> str:
    """Verdict for a security testcase: pass, crash, or an unrecognised exit."""
    if proc.returncode == 0:
        return "pass"
    if extract_sanitizer_block(proc.stderr.decode(errors="ignore")):
        return "crash"
    return f"no matching regex case ({proc.returncode})"


# ---------------------------------------------------------------------------
# Stage driver
# ---------------------------------------------------------------------------


def walk_report(report: dict) -> Iterator[tuple["Task", dict[str, Any]]]:
    """Yield each (task, verdicts) pair of a stage report.

    A report names its configuration once in a header, so the per-task entries
    carry only verdicts.
    """
    config = report.get("config", {})
    for task_id, verdicts in report.get("results", {}).items():
        yield Task(str(task_id), config.get("agent", ""), config.get("model", ""),
                   config.get("tag", "")), verdicts


@dataclass
class Job:
    """One script to execute on behalf of a task.

    ``label`` names the run; a stage that fans one run out into several
    results maps it onto them in ``split``.
    """

    task: Task
    label: str
    command: list[str]


class Stage(ABC):
    """Shared ``setup -> run -> parse -> report`` driver for a stage.

    Subclasses supply the container scripts and the verdict logic; pooling,
    caching and report assembly are handled here.
    """

    #: Directory name under ``out/logs`` and the report filename prefix.
    stage: str = ""
    #: Keys this stage writes into its report for each task.
    result_keys: tuple[str, ...] = ()
    #: Wall-clock budget for one container run, in seconds.
    timeout: int = 3000
    #: Attempts per script. Only upstream rate limiting triggers a retry.
    retries: int = 1

    def __init__(self, paths: Paths = PATHS) -> None:
        self.paths = paths
        self._metadata: dict[str, Any] | None = None

    # -- inputs -------------------------------------------------------------

    @property
    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            self._metadata = json.loads(self.paths.metadata.read_text())
        return self._metadata

    def project_of(self, task: Task) -> str:
        return self.metadata[task.id]["project"]

    # -- subclass hooks -----------------------------------------------------

    @abstractmethod
    def build_scripts(self, task: Task) -> None:
        """Write every container script this task needs."""

    @abstractmethod
    def jobs_for(self, task: Task) -> list[Job]:
        """The scripts to execute for this task, skipping any not written."""

    @abstractmethod
    def parse(self, task: Task, result_key: str, proc: ProcOutput) -> Any:
        """Derive this task's verdict for one result key."""

    def split(self, job: Job, proc: ProcOutput) -> dict[str, ProcOutput]:
        """Map one completed run onto result keys. One-to-one by default."""
        return {job.label: proc}

    def container_name(self, task: Task) -> str:
        """The container this stage runs the task in."""
        return task.container_name(self.stage)

    def run_dir(self, task: Task, result_key: str) -> Path:
        """Where one result's stdout, stderr and cached output are written."""
        return self.paths.log_dir(self.stage, task.id, f"{task.slug}_{result_key}")

    # -- driver -------------------------------------------------------------

    def setup(self, tasks: Sequence[Task], num_workers: int) -> None:
        """Generate every container script, in parallel."""
        if not tasks:
            return
        print(f"[{self.stage}] generating scripts for {len(tasks)} tasks")
        with ProcessPoolExecutor(max_workers=min(num_workers, len(tasks))) as pool:
            futures = {pool.submit(self.build_scripts, t): t for t in tasks}
            with alive_bar(len(futures)) as bar:
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:  # noqa: BLE001 - one task must not abort setup
                        print(f"[{self.stage}] setup failed for {futures[future]}: {exc}")
                    bar()

    def _run_job(self, job: Job) -> tuple[Job, ProcOutput]:
        """Pool worker: run one script and persist its output."""
        # Report the container name, so a line on screen is the same string
        # `docker ps` shows. `job.label` names the results, not the run.
        name = self.container_name(job.task)
        print(f"[{self.stage}] running {name}", flush=True)
        runner = ScriptRunner(timeout=self.timeout, retries=self.retries)
        proc = runner.run(job.command, name, name)
        for result_key, part in self.split(job, proc).items():
            part.save(self.run_dir(job.task, result_key))
        print(f"[{self.stage}] finished {name}", flush=True)
        return job, proc

    def run_jobs(self, jobs: Sequence[Job], num_workers: int) -> list[tuple[Job, ProcOutput]]:
        """Run the jobs across a process pool, tolerating interruption."""
        if not jobs:
            return []
        results: list[tuple[Job, ProcOutput]] = []
        with Pool(min(num_workers, len(jobs))) as pool:
            try:
                with alive_bar(len(jobs)) as bar:
                    for result in pool.imap_unordered(self._run_job, list(jobs)):
                        results.append(result)
                        bar()
            except KeyboardInterrupt:
                print(f"[{self.stage}] interrupted; reporting completed runs")
        return results

    def _cached(self, tasks: Sequence[Task]) -> Iterator[tuple[Task, str, ProcOutput]]:
        """Yield every persisted run, so verdicts can be re-derived cheaply."""
        for task in tasks:
            for result_key in self.result_keys:
                proc = ProcOutput.load(self.run_dir(task, result_key))
                if proc is not None:
                    yield task, result_key, proc

    def run(self, tasks: Sequence[Task], rerun: bool, num_workers: int) -> Path:
        """Execute the stage and write a timestamped report.

        Without ``rerun`` no container is started; verdicts are re-derived from
        a previous run's persisted output.
        """
        results: dict[Task, dict[str, Any]] = {}
        parsed = 0

        if rerun:
            jobs = [job for task in tasks for job in self.jobs_for(task)]
            print(f"[{self.stage}] running {len(jobs)} jobs across {len(tasks)} tasks")
            for job, proc in self.run_jobs(jobs, num_workers):
                for result_key, part in self.split(job, proc).items():
                    self._record(results, job.task, result_key, part)
                    parsed += 1
        else:
            cached = list(self._cached(tasks))
            print(f"[{self.stage}] re-parsing {len(cached)} cached runs "
                  f"({len(tasks) * len(self.result_keys)} expected)")
            with alive_bar(len(cached)) as bar:
                for task, result_key, proc in cached:
                    self._record(results, task, result_key, proc)
                    parsed += 1
                    bar()

        return self.write_report(results, parsed)

    def _record(self, results: dict, task: Task, result_key: str,
                proc: ProcOutput) -> None:
        """Parse one result into the table, isolating parser failures."""
        try:
            verdict = self.parse(task, result_key, proc)
        except Exception as exc:  # noqa: BLE001 - a bad parse must not lose the run
            verdict = f"error: {exc}"
        results.setdefault(task, {})[result_key] = verdict

    def write_report(self, results: dict, parsed: int) -> list[Path]:
        """Write one report per configuration covered by this run."""
        by_config: dict[str, dict] = {}
        for task, verdicts in sorted(results.items()):
            report = by_config.setdefault(
                task.slug, {"config": task.config, "results": {}})
            report["results"][task.id] = verdicts

        self.paths.report_dir(self.stage).mkdir(parents=True, exist_ok=True)
        written = []
        for slug, report in sorted(by_config.items()):
            path = self.paths.report(self.stage, slug)
            path.write_text(json.dumps(report, indent=2))
            print(f"[{self.stage}] wrote {len(report['results'])} results to {path}")
            written.append(path)
        if not written:
            print(f"[{self.stage}] no results to report")
        return written
