from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import run_git

from explog.errors import ConfigError, DirectoryError, GitError, LogError, ScriptError
from explog.initialization import initialize_environment
from explog.log import append_record, read_log


def write_config(
    path: Path,
    *,
    data_root: str = "experiment-data",
    log: str = "experiments.jsonl",
    experiment_scripts: list[list[str]] | None = None,
    processing_scripts: list[list[str]] | None = None,
) -> None:
    path.write_text(
        "\n".join(
            [
                f"log = {json.dumps(log)}",
                f"data_root = {json.dumps(data_root)}",
                f"experiment_scripts = {json.dumps(experiment_scripts or [])}",
                f"data_processing_scripts = {json.dumps(processing_scripts or [])}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_initialize_new_environment_with_relative_paths(
    git_repo: Path, config_file: Path
) -> None:
    result = initialize_environment(
        config_path=Path("explog.toml"),
        log_path=Path("logs/experiments.jsonl"),
        cwd=git_repo,
    )

    assert result.git_root == git_repo
    assert len(result.head) == 40
    assert result.config_path == config_file
    assert result.experiment_commands == 0
    assert result.processing_commands == 0
    assert result.log_created is True
    assert result.existing_records == 0
    assert result.data_root_created is True
    assert result.log_path.read_bytes() == b""
    assert result.data_root == git_repo / "experiment-data"
    assert list(result.data_root.iterdir()) == []


def test_repeated_initialization_preserves_log_and_data(
    git_repo: Path, config_file: Path
) -> None:
    log_path = git_repo / "experiments.jsonl"
    first = initialize_environment(
        config_path=config_file,
        log_path=log_path,
        cwd=git_repo,
    )
    record = {"id": "existing", "message": "keep"}
    append_record(log_path, record)
    marker = first.data_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    second = initialize_environment(
        config_path=config_file,
        log_path=log_path,
        cwd=git_repo,
    )

    assert second.log_created is False
    assert second.existing_records == 1
    assert second.data_root_created is False
    assert read_log(log_path) == [record]
    assert marker.read_text(encoding="utf-8") == "keep"


def test_invalid_existing_log_fails_before_creating_data_root(
    git_repo: Path, config_file: Path
) -> None:
    log_path = git_repo / "bad.jsonl"
    log_path.write_text("not json\n", encoding="utf-8")

    with pytest.raises(LogError, match="invalid JSON"):
        initialize_environment(
            config_path=config_file,
            log_path=log_path,
            cwd=git_repo,
        )

    assert not (git_repo / "experiment-data").exists()


def test_data_root_outside_repository_fails_before_initialization(
    git_repo: Path, config_file: Path
) -> None:
    outside = git_repo.parent / f"outside-{git_repo.name}"
    write_config(config_file, data_root=str(outside))
    log_path = git_repo / "logs" / "experiments.jsonl"

    with pytest.raises(DirectoryError, match="inside Git root"):
        initialize_environment(
            config_path=config_file,
            log_path=log_path,
            cwd=git_repo,
        )

    assert not log_path.parent.exists()
    assert not outside.exists()


def test_data_root_file_conflict_fails_before_log_creation(
    git_repo: Path, config_file: Path
) -> None:
    (git_repo / "experiment-data").write_text("conflict", encoding="utf-8")
    log_path = git_repo / "experiments.jsonl"

    with pytest.raises(DirectoryError, match="not a directory"):
        initialize_environment(
            config_path=config_file,
            log_path=log_path,
            cwd=git_repo,
        )

    assert not log_path.exists()


def test_log_path_cannot_be_an_ancestor_of_data_root(
    git_repo: Path, config_file: Path
) -> None:
    write_config(config_file, data_root="state/data")
    log_path = git_repo / "state"

    with pytest.raises(DirectoryError, match="conflicts with log path"):
        initialize_environment(
            config_path=config_file,
            log_path=log_path,
            cwd=git_repo,
        )

    assert not log_path.exists()


def test_reports_data_root_created_when_log_is_inside_it(
    git_repo: Path, config_file: Path
) -> None:
    result = initialize_environment(
        config_path=config_file,
        log_path=git_repo / "experiment-data" / "experiments.jsonl",
        cwd=git_repo,
    )

    assert result.data_root_created is True
    assert result.log_created is True


def test_missing_script_executable_fails_before_writes(
    git_repo: Path, config_file: Path
) -> None:
    write_config(
        config_file,
        experiment_scripts=[["definitely-missing-explog-executable"]],
    )
    log_path = git_repo / "experiments.jsonl"

    with pytest.raises(ScriptError, match="not available on PATH"):
        initialize_environment(
            config_path=config_file,
            log_path=log_path,
            cwd=git_repo,
        )

    assert not log_path.exists()
    assert not (git_repo / "experiment-data").exists()


def test_accepts_path_and_path_lookup_executables(
    git_repo: Path, config_file: Path
) -> None:
    executable = git_repo / "runner"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    write_config(
        config_file,
        experiment_scripts=[["./runner"]],
        processing_scripts=[[sys.executable]],
    )

    result = initialize_environment(
        config_path=config_file,
        log_path=git_repo / "experiments.jsonl",
        cwd=git_repo,
    )

    assert result.experiment_commands == 1
    assert result.processing_commands == 1


def test_non_git_directory_fails_without_writes(tmp_path: Path) -> None:
    config = tmp_path / "explog.toml"
    write_config(config)

    with pytest.raises(GitError, match="rev-parse"):
        initialize_environment(
            config_path=config,
            log_path=tmp_path / "experiments.jsonl",
            cwd=tmp_path,
        )

    assert not (tmp_path / "experiments.jsonl").exists()
    assert not (tmp_path / "experiment-data").exists()


def test_repository_without_head_fails_without_writes(tmp_path: Path) -> None:
    run_git(tmp_path, "init", "-q")
    config = tmp_path / "explog.toml"
    write_config(config)

    with pytest.raises(GitError, match="rev-parse HEAD"):
        initialize_environment(
            config_path=config,
            log_path=tmp_path / "experiments.jsonl",
            cwd=tmp_path,
        )

    assert not (tmp_path / "experiments.jsonl").exists()
    assert not (tmp_path / "experiment-data").exists()


def test_missing_config_creates_empty_template_without_other_writes(
    git_repo: Path,
) -> None:
    config_path = git_repo / "explog.toml"

    with pytest.raises(ConfigError, match="created empty config template"):
        initialize_environment(config_path=Path("explog.toml"), cwd=git_repo)

    assert config_path.read_text(encoding="utf-8") == (
        'log = ""\n'
        'data_root = ""\n'
        "experiment_scripts = []\n"
        "data_processing_scripts = []\n"
    )
    assert not (git_repo / "experiments.jsonl").exists()
    assert not (git_repo / "experiment-data").exists()


def test_log_path_defaults_to_config_log(git_repo: Path, config_file: Path) -> None:
    result = initialize_environment(
        config_path=Path("explog.toml"),
        cwd=git_repo,
    )

    assert result.log_path == git_repo / "experiments.jsonl"
    assert result.log_created is True
    assert (git_repo / "experiments.jsonl").read_bytes() == b""
