#!/usr/bin/env python3
"""Dispatch a benchmark run using the configuration below."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import ScriptError, main_guard, normalize_returncode, program_name


# Edit these two values to select the architecture and test mode.
ARCH = "riscv32-nemu"
TEST_TYPE = "real"

RUNNER_BY_TEST_TYPE = {
    "real": "run_real.py",
    "single": "run_on_single.py",
    "batch": "run_on_batch.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(sys.argv[0]),
        description="Run the configured benchmark and write logs to DIR.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        type=Path,
        required=True,
        help="existing directory in which log files will be written",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser()
    if not output.is_dir():
        raise ScriptError(
            f"Error: output directory does not exist or is not a directory: {output}",
            2,
        )

    runner_name = RUNNER_BY_TEST_TYPE.get(TEST_TYPE)
    if runner_name is None:
        supported = ", ".join(RUNNER_BY_TEST_TYPE)
        raise ScriptError(
            f"Error: unsupported TEST_TYPE {TEST_TYPE!r}; choose one of: {supported}.",
            2,
        )

    runner = Path(__file__).resolve().parent / "run" / runner_name
    result = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--arch",
            ARCH,
            "--output",
            str(output),
        ],
        check=False,
    )
    return normalize_returncode(result.returncode)


if __name__ == "__main__":
    main_guard(main)
