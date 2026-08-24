"""Shared command-line configuration for benchmark runner scripts."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Runner helpers can also be imported or checked directly; expose shared helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import ScriptError  # noqa: E402


SUPPORTED_ARCHES = ("riscv32-nemu", "riscv32-nemudev")


@dataclass(frozen=True)
class RunConfig:
    arch: str
    output: Path


def make_run_command(microbench: str, arch: str) -> list[str]:
    return ["make", "-C", microbench, f"ARCH={arch}", "run"]


def add_run_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-a",
        "--arch",
        choices=SUPPORTED_ARCHES,
        required=True,
        help="make ARCH value (required on the command line)",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        type=Path,
        required=True,
        help="existing directory in which log files will be written",
    )


def resolve_run_config(args: argparse.Namespace) -> RunConfig:
    arch = args.arch
    if arch is None:
        raise ScriptError("Error: --arch must be provided on the command line.", 2)
    if arch not in SUPPORTED_ARCHES:
        supported = ", ".join(SUPPORTED_ARCHES)
        raise ScriptError(
            f"Error: unsupported ARCH {arch!r}; choose one of: {supported}.", 2
        )

    configured_output = args.output
    if configured_output is None:
        raise ScriptError("Error: --output must be provided on the command line.", 2)
    output = Path(configured_output).expanduser()
    if not output.is_dir():
        raise ScriptError(
            f"Error: output directory does not exist or is not a directory: {output}",
            2,
        )
    return RunConfig(arch=arch, output=output)
