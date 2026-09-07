"""Argument parsing shared by every PatchBench command."""

from __future__ import annotations

import argparse
import json
from abc import ABC, abstractmethod

from ..core.utils import Task
from ..paths import PATHS


class Command(ABC):
    """One subcommand of the ``patchbench`` CLI.

    Every stage is selected by the same axes, so the parser is defined once here
    and subclasses only implement ``execute``.
    """

    name: str = ""
    help: str = ""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agents", nargs="+", required=True,
                            help="Agent frameworks to run, e.g. openhands codex")
        parser.add_argument("--model-names", nargs="+", required=True,
                            help="Models to run under each agent")
        parser.add_argument("--tag", default="",
                            help="Label separating otherwise identical runs; "
                                 "appended to generated names only when set")
        parser.add_argument("--ids", nargs="+",
                            help="Task ids to run (default: every id in metadata.json)")
        parser.add_argument("--num-workers", type=int, default=20,
                            help="Tasks run concurrently")
        parser.add_argument("--rerun", action="store_true",
                            help="Redo work that already has a cached result")
        parser.add_argument("--no-setup", action="store_true",
                            help="Reuse previously generated scripts")

    def tasks(self, args: argparse.Namespace) -> list[Task]:
        """Expand the selected axes into the tasks this invocation covers."""
        ids = args.ids or list(json.loads(PATHS.metadata.read_text()).keys())
        return Task.expand(ids, args.agents, args.model_names, args.tag)

    @abstractmethod
    def execute(self, args: argparse.Namespace) -> None:
        """Run the stage."""
