from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from explog.errors import ExplogError
from explog.initialization import InitializationResult, initialize_environment
from explog.workflow import run_experiment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explog",
        description="Run scripts and append a Git-aware experiment node to JSONL.",
        epilog="Initialize an environment with: explog init --help",
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


def build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explog init",
        description="Check and initialize an explog environment.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("explog.toml"),
        help="TOML config path (default: explog.toml)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("experiments.jsonl"),
        help="JSONL log path (default: experiments.jsonl)",
    )
    return parser


def _print_initialization(result: InitializationResult) -> None:
    print(f"Python: {result.python_version} [OK]")
    print(f"Git repository: {result.git_root} [OK]")
    print(f"HEAD: {result.head} [OK]")
    tracked_note = " [OK]" if result.tracked_changes == 0 else " [modified]"
    print(f"Tracked changes: {result.tracked_changes}{tracked_note}")
    untracked_note = (
        " [OK]" if result.untracked_files == 0 else " [not captured by explog]"
    )
    print(f"Untracked files: {result.untracked_files}{untracked_note}")
    print(f"Config: {result.config_path} [OK]")
    print(f"Experiment commands: {result.experiment_commands} [OK]")
    print(f"Processing commands: {result.processing_commands} [OK]")
    log_status = "created" if result.log_created else "already exists, valid"
    print(f"Log: {result.log_path} [{log_status}; {result.existing_records} records]")
    data_status = "created" if result.data_root_created else "already exists"
    print(f"Data root: {result.data_root} [{data_status}]")
    print("explog environment is ready")


def _run_init(argv: Sequence[str]) -> int:
    arguments = build_init_parser().parse_args(argv)
    try:
        result = initialize_environment(
            config_path=arguments.config,
            log_path=arguments.log,
        )
    except ExplogError as error:
        print(f"explog: error: {error}", file=sys.stderr)
        return 1
    _print_initialization(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    if raw_arguments and raw_arguments[0] == "init":
        return _run_init(raw_arguments[1:])

    arguments = build_parser().parse_args(raw_arguments)
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
