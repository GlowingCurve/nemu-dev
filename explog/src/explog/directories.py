from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from explog.errors import DirectoryError


@dataclass(frozen=True)
class RunDirectories:
    data: Path
    raw: Path
    processed: Path
    relative_data: str


def validate_id(experiment_id: str) -> None:
    if (
        not experiment_id
        or experiment_id in {".", ".."}
        or "/" in experiment_id
        or "\\" in experiment_id
        or "\x00" in experiment_id
        or any(
            ord(character) < 32 or ord(character) == 127 for character in experiment_id
        )
    ):
        raise DirectoryError(
            "id must be a non-empty, safe, single-directory name without separators"
        )


def plan_directories(
    git_root: Path, configured_data_root: Path, experiment_id: str
) -> RunDirectories:
    validate_id(experiment_id)
    try:
        if configured_data_root.is_absolute():
            data_root = configured_data_root.resolve()
        else:
            data_root = (git_root / configured_data_root).resolve()
    except (OSError, RuntimeError) as error:
        raise DirectoryError(
            f"cannot resolve data_root: {configured_data_root}"
        ) from error

    try:
        data_root.relative_to(git_root)
    except ValueError as error:
        raise DirectoryError(
            f"data_root must be inside Git root: {data_root}"
        ) from error

    try:
        if data_root.exists() and not data_root.is_dir():
            raise DirectoryError(f"data_root is not a directory: {data_root}")
    except OSError as error:
        raise DirectoryError(f"cannot inspect data_root: {data_root}") from error

    data = data_root / experiment_id
    try:
        relative_data = data.relative_to(git_root).as_posix()
    except ValueError as error:
        raise DirectoryError(
            f"data directory must be inside Git root: {data}"
        ) from error

    try:
        if data.exists():
            raise DirectoryError(f"data directory already exists: {data}")
    except OSError as error:
        raise DirectoryError(f"cannot inspect data directory: {data}") from error
    return RunDirectories(
        data=data,
        raw=data / "raw",
        processed=data / "processed",
        relative_data=relative_data,
    )


def create_directories(directories: RunDirectories) -> None:
    try:
        directories.data.mkdir(parents=True, exist_ok=False)
        directories.raw.mkdir()
        directories.processed.mkdir()
    except OSError as error:
        raise DirectoryError(
            f"cannot create data directories at {directories.data}: {error}"
        ) from error
