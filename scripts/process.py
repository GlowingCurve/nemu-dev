#!/usr/bin/env python3
"""Dispatch log processing using the shared configuration."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from _common import ScriptError, main_guard, normalize_returncode, program_name
from _config import LOG_TYPE

ANALYZER_BY_LOG_TYPE = {
    "real": "analyze_real.py",
    "batch": "analyze_batch.py",
    "single": "analyze_single.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(sys.argv[0]),
        description="Process logs using the configured log data type.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--input",
        metavar="DIR",
        type=Path,
        required=True,
        help="directory containing the input log files",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        type=Path,
        required=True,
        help="directory in which analysis results will be written",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    analyzer_name = ANALYZER_BY_LOG_TYPE.get(LOG_TYPE)
    if analyzer_name is None:
        supported = ", ".join(ANALYZER_BY_LOG_TYPE)
        raise ScriptError(
            f"Error: unsupported LOG_TYPE {LOG_TYPE!r}; choose one of: {supported}.",
            2,
        )

    analyzer = Path(__file__).resolve().parent / "analyze" / analyzer_name
    result = subprocess.run(
        [
            sys.executable,
            str(analyzer),
            "--input",
            str(args.input.expanduser()),
            "--output",
            str(args.output.expanduser()),
        ],
        check=False,
    )
    return normalize_returncode(result.returncode)


if __name__ == "__main__":
    main_guard(main)
