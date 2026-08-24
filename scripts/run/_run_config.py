"""Shared command-line configuration for benchmark runner scripts."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Runner helpers can also be imported or checked directly; expose shared helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import ScriptError  # noqa: E402


SUPPORTED_ARCHES = ("riscv32-nemu", "riscv32-nemudev")
BUILD_HOME_ENV_BY_ARCH = {
    "riscv32-nemu": "NEMU_HOME",
    "riscv32-nemudev": "NEMUDEV_HOME",
}
COMPILE_FLAG_FILENAMES = ("compile_cflags", "compile_ldflags")


@dataclass(frozen=True)
class RunConfig:
    arch: str
    output: Path


def make_run_command(microbench: str, arch: str) -> list[str]:
    return ["make", "-C", microbench, f"ARCH={arch}", "run"]


def copy_compile_flags(config: RunConfig) -> None:
    home_environment = BUILD_HOME_ENV_BY_ARCH[config.arch]
    configured_home = os.environ.get(home_environment)
    if not configured_home:
        raise ScriptError(f"Error: {home_environment} is not set.", 2)

    build_directory = Path(configured_home).expanduser() / "build"
    sources = [build_directory / name for name in COMPILE_FLAG_FILENAMES]
    missing_sources = [source for source in sources if not source.is_file()]
    if missing_sources:
        missing = ", ".join(map(str, missing_sources))
        raise ScriptError(f"Error: compile flag file does not exist: {missing}", 2)

    destinations = [config.output / name for name in COMPILE_FLAG_FILENAMES]
    conflicts = [
        destination
        for destination in destinations
        if destination.exists() or destination.is_symlink()
    ]
    if conflicts:
        existing = ", ".join(map(str, conflicts))
        raise ScriptError(
            f"Error: output compile flag path already exists: {existing}", 2
        )

    for source, destination in zip(sources, destinations, strict=True):
        shutil.copy2(source, destination)


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
