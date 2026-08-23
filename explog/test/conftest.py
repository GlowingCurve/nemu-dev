from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.name", "Explog Tests")
    run_git(tmp_path, "config", "user.email", "explog@example.invalid")
    (tmp_path / "tracked.txt").write_text("initial\n", encoding="utf-8")
    run_git(tmp_path, "add", "tracked.txt")
    run_git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


@pytest.fixture
def config_file(git_repo: Path) -> Path:
    path = git_repo / "explog.toml"
    path.write_text(
        "\n".join(
            [
                'data_root = "experiment-data"',
                "experiment_scripts = []",
                "data_processing_scripts = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path
