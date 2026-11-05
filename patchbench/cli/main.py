"""Entry point: ``patchbench <stage> --agents ... --model-names ...``."""

from __future__ import annotations

import argparse
import json
import sys

from ..config.constants import DEFAULT_EFFORT, EFFORT_LEVELS, MODELS
from ..core.corpus_replay import CorpusReplay
from ..core.inference import Inference
from ..core.output_match import OutputMatch
from ..core.poc_replay import PocReplay
from ..core.scoreboard import Scoreboard
from ..core.unit_tests import UnitTests
from ..core.utils import Task
from ..paths import PATHS
from .base import Command


class StageCommand(Command):
    """Runs one stage over the selected tasks and writes its report.

    Every stage is selected by the same axes, so their flags are defined once
    here.
    """

    stage_class: type = None

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agents", nargs="+", required=True,
                            help="Agent frameworks to run, e.g. openhands codex")
        parser.add_argument("--model-names", nargs="+", required=True,
                            choices=MODELS, metavar="M",
                            help="Models to run under each agent, by their name "
                                 "in MODELS (patchbench/config/constants.py)")
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

    def make_stage(self, args: argparse.Namespace):
        return self.stage_class()

    def execute(self, args: argparse.Namespace) -> None:
        stage = self.make_stage(args)
        tasks = self.tasks(args)
        if not args.no_setup:
            stage.setup(tasks, args.num_workers)
        stage.run(tasks, args.rerun, args.num_workers)


class InferCommand(StageCommand):
    """Runs each agent against its task and collects the patch it produces."""

    name = "infer"
    help = "Run agents on the benchmark tasks and collect their patches"
    stage_class = Inference

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        super().add_arguments(parser)
        parser.add_argument("--effort", choices=EFFORT_LEVELS, default=DEFAULT_EFFORT,
                            help="Claude Code's effort level (default: %(default)s); "
                                 "OpenHands and Codex keep their own setting")

    def make_stage(self, args: argparse.Namespace) -> Inference:
        return Inference(effort=args.effort)


class PocCommand(StageCommand):
    """Replays the vulnerability's PoC against each patched build."""

    name = "poc"
    help = "Replay the proof-of-concept against patched builds"
    stage_class = PocReplay


class UnitTestCommand(StageCommand):
    """Runs each project's own test suite against the patched build."""

    name = "unittest"
    help = "Run the projects' unit tests against patched builds"
    stage_class = UnitTests


class ReplayCommand(StageCommand):
    """Replays the recorded corpus against each patched build."""

    name = "replay"
    help = "Replay the recorded corpus against patched builds"
    stage_class = CorpusReplay


class VerifyCommand(StageCommand):
    """Checks that each patched build still reproduces the reference outputs."""

    name = "verify"
    help = "Check patched builds still produce byte-identical output"
    stage_class = OutputMatch


class AnalyzeCommand(Command):
    """Combines every stage's report into one scored table.

    Takes no task selection: the stage reports already record what was run.
    """

    name = "analyze"
    help = "Combine the stage reports into per-task results and grouped metrics"

    def execute(self, args: argparse.Namespace) -> None:
        Scoreboard().analyze()


COMMANDS: list[Command] = [
    InferCommand(), PocCommand(), UnitTestCommand(),
    ReplayCommand(), VerifyCommand(), AnalyzeCommand(),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="patchbench", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        sub = subparsers.add_parser(command.name, help=command.help)
        command.add_arguments(sub)
        sub.set_defaults(handler=command)
    return parser


def main(argv: list[str] | None = None) -> int:
    # The working tree comes from $PATCHBENCH_ROOT, read when paths are imported.
    args = build_parser().parse_args(argv)
    PATHS.ensure_outputs()
    args.handler.execute(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
