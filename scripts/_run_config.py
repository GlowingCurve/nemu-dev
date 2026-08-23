"""Shared command-line configuration for benchmark runner scripts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from _common import ScriptError


SUPPORTED_ARCHES = ("riscv32-nemu", "riscv32-nemudev")


@dataclass(frozen=True)
class RunConfig:
    arch: str
    log_root: Path


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
        "--log-root",
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

    configured_root = args.log_root
    if configured_root is None:
        raise ScriptError("Error: --log-root must be provided on the command line.", 2)
    log_root = Path(configured_root).expanduser()
    if not log_root.is_dir():
        raise ScriptError(
            f"Error: output directory does not exist or is not a directory: {log_root}",
            2,
        )
    return RunConfig(arch=arch, log_root=log_root)
