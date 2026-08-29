from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from explog.config import load_config
from explog.errors import ExplogError
from explog.initialization import InitializationResult, initialize_environment
from explog.listing import format_nodes, list_nodes
from explog.workflow import run_experiment


def _add_run_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run",
        help="run scripts and record an experiment",
        description="Run scripts and append a Git-aware experiment node to JSONL.",
    )
    parser.add_argument("--config", required=True, type=Path, help="TOML config path")
    parser.add_argument(
        "--log",
        type=Path,
        help="JSONL log path (default: log path from the config file)",
    )
    parser.add_argument("--message", required=True, help="experiment message")
    parser.add_argument(
        "--parent-id", metavar="ID", help="existing parent experiment ID"
    )
    parser.add_argument(
        "--id", dest="experiment_id", metavar="ID", help="custom experiment ID"
    )
    parser.set_defaults(handler=_run_experiment)


def _add_init_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "init",
        help="check and initialize an explog environment",
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
        help="JSONL log path (default: log path from the config file)",
    )
    parser.set_defaults(handler=_run_init)


def _add_list_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "list",
        help="list experiments in chronological order",
        description="List experiments from a JSONL log in chronological order.",
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
        help="JSONL log path (default: log path from the config file)",
    )
    parser.set_defaults(handler=_run_list)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="explog",
        description="Run and inspect Git-aware experiments recorded in JSONL.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_run_parser(subparsers)
    _add_init_parser(subparsers)
    _add_list_parser(subparsers)
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


def _run_init(arguments: argparse.Namespace) -> int:
    result = initialize_environment(
        config_path=arguments.config,
        log_path=arguments.log,
    )
    _print_initialization(result)
    return 0


def _run_experiment(arguments: argparse.Namespace) -> int:
    node = run_experiment(
        config_path=arguments.config,
        log_path=arguments.log,
        message=arguments.message,
        parent_id=arguments.parent_id,
        experiment_id=arguments.experiment_id,
    )
    print(node.id)
    return 0


def _run_list(arguments: argparse.Namespace) -> int:
    log_path = arguments.log
    if log_path is None:
        config_path = arguments.config
        config = load_config(config_path)
        log_path = (config_path.resolve().parent / config.log).resolve()
    output = format_nodes(list_nodes(log_path))
    if output:
        print(output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return arguments.handler(arguments)
    except ExplogError as error:
        print(f"explog: error: {error}", file=sys.stderr)
        return 1
