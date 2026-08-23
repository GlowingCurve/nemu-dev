from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from explog.errors import ExplogError
from explog.workflow import run_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explog",
        description="Run scripts and append a Git-aware experiment node to JSONL.",
    )
    parser.add_argument("--config", required=True, type=Path, help="TOML config path")
    parser.add_argument("--log", required=True, type=Path, help="JSONL log path")
    parser.add_argument("--message", required=True, help="experiment message")
    parser.add_argument(
        "--parent-id", metavar="ID", help="existing parent experiment ID"
    )
    parser.add_argument(
        "--id", dest="experiment_id", metavar="ID", help="custom experiment ID"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        node = run_experiment(
            config_path=arguments.config,
            log_path=arguments.log,
            message=arguments.message,
            parent_id=arguments.parent_id,
            experiment_id=arguments.experiment_id,
        )
    except ExplogError as error:
        print(f"explog: error: {error}", file=sys.stderr)
        return 1
    print(node.id)
    return 0
