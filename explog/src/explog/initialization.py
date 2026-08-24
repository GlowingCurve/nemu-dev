from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

from explog.config import Config, load_config
from explog.directories import create_data_root, resolve_data_root
from explog.errors import ConfigError, DirectoryError, LogError, ScriptError
from explog.git import find_git_root, inspect_repository
from explog.log import create_log_parent, initialize_log, read_log


@dataclass(frozen=True)
class InitializationResult:
    python_version: str
    git_root: Path
    head: str
    tracked_changes: int
    untracked_files: int
    config_path: Path
    experiment_commands: int
    processing_commands: int
    log_path: Path
    log_created: bool
    existing_records: int
    data_root: Path
    data_root_created: bool


def _resolve_cli_path(path: Path, working_directory: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (working_directory / path).resolve()


def _check_executable(executable: str, git_root: Path) -> None:
    path = Path(executable)
    has_separator = os.sep in executable or (
        os.altsep is not None and os.altsep in executable
    )
    if path.is_absolute() or has_separator:
        candidate = path if path.is_absolute() else git_root / path
        try:
            available = candidate.is_file() and os.access(candidate, os.X_OK)
        except OSError as error:
            raise ScriptError(
                f"cannot inspect script executable {executable}: {error}"
            ) from error
        if not available:
            raise ScriptError(f"script executable is not available: {executable}")
        return

    if shutil.which(executable) is None:
        raise ScriptError(f"script executable is not available on PATH: {executable}")


def _check_commands(config: Config, git_root: Path) -> None:
    commands = (*config.experiment_scripts, *config.data_processing_scripts)
    for command in commands:
        _check_executable(command[0], git_root)


def initialize_environment(
    *,
    config_path: Path,
    log_path: Path,
    cwd: Path | None = None,
) -> InitializationResult:
    """Validate and initialize the shared files required by explog."""
    try:
        working_directory = (cwd or Path.cwd()).resolve()
    except (OSError, RuntimeError) as error:
        raise DirectoryError("cannot resolve working directory") from error
    try:
        resolved_config = _resolve_cli_path(config_path, working_directory)
    except (OSError, RuntimeError) as error:
        raise ConfigError(f"cannot resolve config path: {config_path}") from error
    try:
        resolved_log = _resolve_cli_path(log_path, working_directory)
    except (OSError, RuntimeError) as error:
        raise LogError(f"cannot resolve log path: {log_path}") from error

    git_root = find_git_root(working_directory)
    repository = inspect_repository(git_root)
    config = load_config(resolved_config)
    _check_commands(config, git_root)
    data_root = resolve_data_root(git_root, config.data_root)
    if data_root == resolved_log or data_root.is_relative_to(resolved_log):
        raise DirectoryError(
            f"data_root conflicts with log path: {data_root} and {resolved_log}"
        )

    records = read_log(resolved_log)

    data_root_existed = data_root.exists()
    create_log_parent(resolved_log)
    created_directly = create_data_root(data_root)
    data_root_created = created_directly or not data_root_existed
    log_created = initialize_log(resolved_log)

    return InitializationResult(
        python_version=platform.python_version(),
        git_root=git_root,
        head=repository.head,
        tracked_changes=repository.tracked_changes,
        untracked_files=repository.untracked_files,
        config_path=resolved_config,
        experiment_commands=len(config.experiment_scripts),
        processing_commands=len(config.data_processing_scripts),
        log_path=resolved_log,
        log_created=log_created,
        existing_records=len(records),
        data_root=data_root,
        data_root_created=data_root_created,
    )
