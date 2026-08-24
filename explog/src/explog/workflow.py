from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from explog.config import load_config
from explog.directories import create_directories, plan_directories, validate_id
from explog.errors import LogError
from explog.git import capture_snapshot, find_git_root, write_diff_file
from explog.log import append_record, read_log
from explog.model import ExperimentNode
from explog.scripts import run_experiment_scripts, run_processing_scripts


def generate_id(timestamp_seconds: int | None = None) -> str:
    value = int(time.time()) if timestamp_seconds is None else timestamp_seconds
    moment = datetime.fromtimestamp(value, UTC)
    return f"{moment:%Y%m%dT%H%M%SZ}"


def _creation_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_log_state(
    records: list[dict[str, object]], experiment_id: str, parent_id: str | None
) -> None:
    existing_ids = {record["id"] for record in records}
    if experiment_id in existing_ids:
        raise LogError(f"experiment id already exists in log: {experiment_id}")
    if parent_id is not None and parent_id not in existing_ids:
        raise LogError(f"parent id does not exist in log: {parent_id}")


def run_experiment(
    *,
    config_path: Path,
    log_path: Path,
    message: str,
    parent_id: str | None = None,
    experiment_id: str | None = None,
    cwd: Path | None = None,
) -> ExperimentNode:
    """Run one experiment and append its node after every script succeeds."""
    working_directory = (cwd or Path.cwd()).resolve()

    # Preflight: all validation happens before the Git snapshot or any writes.
    config = load_config(config_path)
    git_root = find_git_root(working_directory)
    chosen_id = generate_id() if experiment_id is None else experiment_id
    validate_id(chosen_id)
    records = read_log(log_path)
    _validate_log_state(records, chosen_id, parent_id)
    directories = plan_directories(git_root, config.data_root, chosen_id)
    if not log_path.parent.is_dir():
        raise LogError(f"log parent directory does not exist: {log_path.parent}")

    snapshot = capture_snapshot(git_root)
    create_directories(directories)
    write_diff_file(directories.git_diff, snapshot.diff)
    run_experiment_scripts(config.experiment_scripts, directories.raw, git_root)
    run_processing_scripts(
        config.data_processing_scripts,
        directories.raw,
        directories.processed,
        git_root,
    )

    node = ExperimentNode(
        id=chosen_id,
        parent_id=parent_id,
        timestamp=_creation_timestamp(),
        message=message,
        git_commit=snapshot.head,
        git_diff_path=directories.relative_git_diff,
        data_dir=directories.relative_data,
    )
    append_record(log_path, asdict(node))
    return node
