"""Entry point: ``patchbench <stage> --agents ... --model-names ...``."""

from __future__ import annotations

import argparse
import sys

from ..core.corpus_replay import CorpusReplay
from ..core.inference import Inference
from ..core.output_match import OutputMatch
from ..core.poc_replay import PocReplay
from ..core.scoreboard import Scoreboard
from ..core.unit_tests import UnitTests
from ..paths import PATHS
from .base import Command


class StageCommand(Command):
    """Runs one stage over the selected tasks and writes its report."""

    stage_class: type = None

    def execute(self, args: argparse.Namespace) -> None:
        stage = self.stage_class()
        tasks = self.tasks(args)
        if not args.no_setup:
            stage.setup(tasks, args.num_workers)
        stage.run(tasks, args.rerun, args.num_workers)


class InferCommand(StageCommand):
    """Runs each agent against its task and collects the patch it produces."""

    name = "infer"
    help = "Run agents on the benchmark tasks and collect their patches"
    stage_class = Inference


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

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        pass

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
