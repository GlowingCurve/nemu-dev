from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from explog.errors import LogError


def read_log(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            if path.is_symlink():
                raise LogError(f"log path is a broken symbolic link: {path}")
            return []
        if not path.is_file():
            raise LogError(f"log path is not a regular file: {path}")
    except (OSError, ValueError) as error:
        raise LogError(f"cannot inspect log {path}: {error}") from error

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    try:
        with path.open(encoding="utf-8") as log_file:
            for line_number, line in enumerate(log_file, start=1):
                if not line.strip():
                    raise LogError(f"blank line in {path} at line {line_number}")
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise LogError(
                        f"invalid JSON in {path} at line {line_number}: {error.msg}"
                    ) from error
                if not isinstance(record, dict):
                    raise LogError(
                        f"log record in {path} at line {line_number} is not an object"
                    )
                record_id = record.get("id")
                if not isinstance(record_id, str) or not record_id:
                    raise LogError(
                        f"log record in {path} at line {line_number} has no valid id"
                    )
                if record_id in seen_ids:
                    raise LogError(f"duplicate id in existing log: {record_id}")
                seen_ids.add(record_id)
                records.append(record)
    except UnicodeError as error:
        raise LogError(f"log is not valid UTF-8: {path}") from error
    except OSError as error:
        raise LogError(f"cannot read log {path}: {error}") from error
    return records


def append_record(path: Path, record: Mapping[str, Any]) -> None:
    try:
        serialized = json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with path.open("a", encoding="utf-8", newline="") as log_file:
            log_file.write(f"{serialized}\n")
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        raise LogError(f"cannot append log {path}: {error}") from error


def create_log_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise LogError(
            f"cannot create log parent directory {path.parent}: {error}"
        ) from error


def initialize_log(path: Path) -> bool:
    try:
        with path.open("x", encoding="utf-8", newline=""):
            pass
    except FileExistsError:
        # Another initializer may have created the file after preflight.
        read_log(path)
        return False
    except (OSError, UnicodeError, ValueError) as error:
        raise LogError(f"cannot initialize log {path}: {error}") from error
    return True
