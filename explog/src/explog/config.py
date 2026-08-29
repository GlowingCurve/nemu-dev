from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from explog.errors import ConfigError


@dataclass(frozen=True)
class Config:
    log: Path
    data_root: Path
    experiment_scripts: tuple[tuple[str, ...], ...]
    data_processing_scripts: tuple[tuple[str, ...], ...]


_CONFIG_KEYS = {
    "log",
    "data_root",
    "experiment_scripts",
    "data_processing_scripts",
}


def _parse_commands(value: Any, key: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{key} must be an array of argv arrays")

    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(value):
        if not isinstance(command, list) or not command:
            raise ConfigError(f"{key}[{index}] must be a non-empty argv array")
        if not all(isinstance(argument, str) for argument in command):
            raise ConfigError(f"{key}[{index}] arguments must all be strings")
        if not command[0]:
            raise ConfigError(f"{key}[{index}] executable must not be empty")
        commands.append(tuple(command))
    return tuple(commands)


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        raise ConfigError(f"cannot load config {path}: {error}") from error

    unknown = set(raw) - _CONFIG_KEYS
    missing = _CONFIG_KEYS - set(raw)
    if missing:
        raise ConfigError(f"missing config key(s): {', '.join(sorted(missing))}")
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(sorted(unknown))}")

    log = raw["log"]
    if not isinstance(log, str) or not log:
        raise ConfigError("log must be a non-empty string")
    if "\x00" in log:
        raise ConfigError("log must not contain a NUL character")

    data_root = raw["data_root"]
    if not isinstance(data_root, str) or not data_root:
        raise ConfigError("data_root must be a non-empty string")
    if "\x00" in data_root:
        raise ConfigError("data_root must not contain a NUL character")

    return Config(
        log=Path(log),
        data_root=Path(data_root),
        experiment_scripts=_parse_commands(
            raw["experiment_scripts"], "experiment_scripts"
        ),
        data_processing_scripts=_parse_commands(
            raw["data_processing_scripts"], "data_processing_scripts"
        ),
    )
