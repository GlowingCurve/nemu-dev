from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path

from explog.errors import ScriptError


def _run(command: Sequence[str], arguments: Sequence[str], cwd: Path) -> None:
    full_command = [*command, *arguments]
    try:
        result = subprocess.run(full_command, cwd=cwd, check=False, shell=False)
    except (OSError, ValueError) as error:
        raise ScriptError(
            f"cannot run script {shlex.join(full_command)}: {error}"
        ) from error
    if result.returncode != 0:
        raise ScriptError(
            f"script failed with exit status {result.returncode}: "
            f"{shlex.join(full_command)}"
        )


def run_experiment_scripts(
    commands: Sequence[Sequence[str]], output: Path, git_root: Path
) -> None:
    for command in commands:
        _run(command, ["--output", str(output)], git_root)


def run_processing_scripts(
    commands: Sequence[Sequence[str]], input_path: Path, output: Path, git_root: Path
) -> None:
    for command in commands:
        _run(
            command,
            ["--input", str(input_path), "--output", str(output)],
            git_root,
        )
