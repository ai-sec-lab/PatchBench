"""Combines every stage's report into one table of per-task results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterator

import pandas as pd

from ..paths import PATHS, Paths
from .utils import Task, walk_report


class Scoreboard:
    """Joins the five stage reports on task identity and scores the result.

    Each stage writes its own report independently; this reads whichever of
    them exist and puts one row per task on the table, so a partial run still
    analyzes.
    """

    #: Columns identifying a run, grouped over when aggregating.
    GROUP_COLUMNS = ["agent", "model", "tag"]

    #: Columns aggregated in the summary. Every one is 0/1 so it can be averaged;
    #: the diagnostic columns stay in the per-task tables.
    SCORED_COLUMNS = ["patch_produced", "poc_pass", "build_failed", "unittest_pass",
                      "replay_c1", "replay_c2", "replay_pass", "verify_pass"]

    def __init__(self, paths: Paths = PATHS) -> None:
        self.paths = paths
        self._metadata: dict[str, Any] | None = None
        self._base: dict[str, Any] | None = None

        #: Stage reports read, in column order. Naming the decoders explicitly
        #: means renaming a stage breaks here rather than silently reading
        #: nothing.
        self.decoders: dict[str, Callable[[Task, dict], dict[str, Any]]] = {
            "infer": self.decode_infer,
            "poc": self.decode_poc,
            "unittest": self.decode_unittest,
            "replay": self.decode_replay,
            "verify": self.decode_verify,
        }

    # -- inputs -------------------------------------------------------------

    @property
    def metadata(self) -> dict[str, Any]:
        if self._metadata is None:
            self._metadata = json.loads(self.paths.metadata.read_text())
        return self._metadata

    @property
    def base_report(self) -> dict[str, Any]:
        """Reference results for the unpatched build: the unit-test answer key."""
        if self._base is None:
            self._base = json.loads(self.paths.base_report.read_text())
        return self._base

    # -- per-stage columns --------------------------------------------------

    def decode_infer(self, task: Task, verdicts: dict) -> dict[str, Any]:
        patch = verdicts.get("patch") or {}
        return {"patch_produced": int(bool(patch.get("produced")))}

    def decode_poc(self, task: Task, verdicts: dict) -> dict[str, Any]:
        """A build that produced neither a pass nor a crash never compiled."""
        result = verdicts.get("poc")
        return {
            "poc": result,
            "poc_pass": int(result == "pass"),
            "build_failed": int(result not in ("pass", "crash")),
        }

    def decode_unittest(self, task: Task, verdicts: dict) -> dict[str, Any]:
        """Whether the patch still passes every test the reference run passed.

        A verdict that is not a breakdown -- a parse failure, or a project with
        no reader -- yields no column rather than a confident failure, so
        "could not judge" stays distinguishable from "failed".
        """
        result = verdicts.get("unittest")
        if not isinstance(result, dict) or task.id not in self.base_report:
            return {}
        expected = set(self.base_report[task.id]["unittest_sec"]["pass"])
        missing = expected - set(result.get("pass", []))
        return {"unittest_pass": int(not missing)}

    def decode_replay(self, task: Task, verdicts: dict) -> dict[str, Any]:
        c1 = int(verdicts.get("C1") == "pass")
        c2 = int(verdicts.get("C2") == "pass")
        return {"replay_c1": c1, "replay_c2": c2, "replay_pass": c1 & c2}

    def decode_verify(self, task: Task, verdicts: dict) -> dict[str, Any]:
        return {"verify_pass": int(verdicts.get("verify") or 0)}

    # -- assembly -----------------------------------------------------------

    def rows(self) -> dict[Task, dict[str, Any]]:
        """One row per task, merging whichever stage reports are present."""
        rows: dict[Task, dict[str, Any]] = {}
        for stage, decode in self.decoders.items():
            paths = sorted(self.paths.report_dir(stage).glob("*.json"))
            if not paths:
                print(f"[analyze] no {stage} reports under "
                      f"{self.paths.report_dir(stage)}, skipping")
                continue
            reports = [json.loads(p.read_text()) for p in paths]
            print(f"[analyze] {stage}: {len(paths)} configuration(s)")
            for task, verdicts in (r for rep in reports for r in walk_report(rep)):
                row = rows.setdefault(task, {
                    "id": task.id,
                    "project_name": self.metadata.get(task.id, {}).get("project", ""),
                    "agent": task.agent,
                    "model": task.model_name,
                    "tag": task.tag,
                })
                row.update(decode(task, verdicts))
        return rows

    def grouped(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mean and count of every scored column, per configuration."""
        aggregations = {}
        for column in self.SCORED_COLUMNS:
            if column in df.columns:
                aggregations[f"avg_{column}"] = (column, "mean")
                aggregations[f"num_{column}"] = (column, "sum")
        grouped = df.groupby(self.GROUP_COLUMNS, dropna=False).agg(
            num_samples=("id", "size"), **aggregations)
        return grouped.round(4).reset_index()

    def analyze(self) -> list[Path]:
        """Write one table per configuration, plus the summary across them."""
        self.paths.results.mkdir(parents=True, exist_ok=True)
        by_config: dict[str, list[dict[str, Any]]] = {}
        for task, row in sorted(self.rows().items()):
            by_config.setdefault(task.slug, []).append(row)

        if not by_config:
            print("[analyze] no stage reports found")
            pd.DataFrame().to_csv(self.paths.summary, index=False)
            return [self.paths.summary]

        written, frames = [], []
        for slug, rows in sorted(by_config.items()):
            df = pd.DataFrame(rows)
            path = self.paths.result(slug)
            df.to_csv(path, index=False)
            print(f"[analyze] wrote {len(df)} rows to {path}")
            written.append(path)
            frames.append(df)

        self.grouped(pd.concat(frames, ignore_index=True)).to_csv(
            self.paths.summary, index=False)
        print(f"[analyze] wrote {len(frames)} configuration(s) to {self.paths.summary}")
        return written + [self.paths.summary]
