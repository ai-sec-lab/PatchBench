"""The interface every PatchBench command implements."""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod


class Command(ABC):
    """One subcommand of the ``patchbench`` CLI."""

    name: str = ""
    help: str = ""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add this command's flags. A command takes none unless it says so."""

    @abstractmethod
    def execute(self, args: argparse.Namespace) -> None:
        """Run the command."""
