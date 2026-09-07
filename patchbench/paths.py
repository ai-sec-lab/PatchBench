"""Filesystem layout for a PatchBench working tree.

Every path the benchmark reads or writes is resolved here, so that a run is
pinned to one root instead of to the process working directory. Point
``PATCHBENCH_ROOT`` at a working tree to run from anywhere; it defaults to the
directory containing this package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

_ENV_ROOT = "PATCHBENCH_ROOT"


@dataclass(frozen=True)
class Paths:
    """Resolved locations of every benchmark input and output."""

    root: Path

    @classmethod
    def resolve(cls, root: str | os.PathLike | None = None) -> "Paths":
        if root is None:
            root = os.environ.get(_ENV_ROOT) or Path(__file__).resolve().parent.parent
        return cls(root=Path(root).resolve())

    # -- inputs, shipped with the benchmark ---------------------------------

    @cached_property
    def metadata(self) -> Path:
        """Task metadata, including the ground-truth patch. Host-side only."""
        return self.root / "data" / "metadata.json"

    @cached_property
    def base_report(self) -> Path:
        """Unit-test results on the reference-patched repositories (the answer
        key): the tests a correct fix is expected to leave passing."""
        return self.root / "data" / "unittest.json"

    @cached_property
    def corpus_valid(self) -> Path:
        """Per-task list of corpus inputs with a known-good reference output."""
        return self.root / "data" / "corpus_valid.json"

    @cached_property
    def fuzz_targets(self) -> Path:
        """Per-task fuzz-target source, binary and output paths inside the image."""
        return self.root / "data" / "fuzz_targets.csv"

    @cached_property
    def corpus(self) -> Path:
        """Fuzzing corpus, one ``{id}/{C1,C2}/`` directory per task."""
        return self.root / "data" / "corpus"

    @cached_property
    def corpus_outputs(self) -> Path:
        """Reference outputs replayed inputs are compared against."""
        return self.root / "data" / "corpus_outputs"

    @cached_property
    def instrumented_targets(self) -> Path:
        """Instrumented fuzz-target sources transplanted in during verification."""
        return self.root / "data" / "instrumented_targets"

    @cached_property
    def harnesses(self) -> Path:
        """Agent harnesses -- the only "harness" in the tree. Mounted into the
        inference container wholesale."""
        return self.root / "harnesses"

    # -- outputs, produced by a run -----------------------------------------

    @cached_property
    def diffs(self) -> Path:
        """Agent-produced patches, one ``{id}/`` directory per task."""
        return self.root / "out" / "diffs"

    @cached_property
    def scripts(self) -> Path:
        """Generated ``docker run`` scripts, one directory per stage and task."""
        return self.root / "out" / "scripts"

    @cached_property
    def work(self) -> Path:
        """Scratch checkouts for host-side agents, removed after each run."""
        return self.root / "out" / "work"

    @cached_property
    def logs(self) -> Path:
        """Container stdout/stderr, one directory per stage and task."""
        return self.root / "out" / "logs"

    @cached_property
    def reports(self) -> Path:
        """Stage reports, one JSON file per stage."""
        return self.root / "out" / "reports"

    @cached_property
    def results(self) -> Path:
        """Analyzed reports: per-task CSV rows and the cross-run summary."""
        return self.root / "out" / "results"

    # -- helpers ------------------------------------------------------------

    def diff_dir(self, task_id: str) -> Path:
        return self.diffs / str(task_id)

    def log_dir(self, stage: str, task_id: str, name: str) -> Path:
        """Where one container run's stdout, stderr and cache are written."""
        return self.logs / stage / str(task_id) / name

    def report_dir(self, stage: str) -> Path:
        """Every report this stage has written, one file per configuration."""
        return self.reports / stage

    def report(self, stage: str, slug: str) -> Path:
        """One stage's report for one configuration, rewritten by each run.

        Naming by configuration keeps separate runs -- a second model, a second
        agent -- from overwriting each other's results.
        """
        return self.report_dir(stage) / f"{slug}.json"

    def result(self, slug: str) -> Path:
        """One configuration's per-task table."""
        return self.results / f"{slug}.csv"

    @property
    def summary(self) -> Path:
        """One row per configuration, across every result table."""
        return self.results / "summary.csv"

    def work_dir(self, task_id: str, slug: str) -> Path:
        """Where one host-side run extracts the repository to."""
        return self.work / str(task_id) / slug

    def script_dir(self, stage: str, task_id: str) -> Path:
        """Where a stage's generated scripts for one task are written."""
        return self.scripts / stage / str(task_id)

    def ensure_outputs(self) -> None:
        """Create the output tree. Inputs are never created implicitly."""
        for path in (self.diffs, self.scripts,
                     self.logs, self.reports, self.results):
            path.mkdir(parents=True, exist_ok=True)


PATHS = Paths.resolve()
