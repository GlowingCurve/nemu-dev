from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from explog.errors import GitError


@dataclass(frozen=True)
class GitSnapshot:
    root: Path
    head: str
    diff: str


def _git(arguments: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError) as error:
        raise GitError(f"cannot run git: {error}") from error

    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise GitError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


def find_git_root(cwd: Path) -> Path:
    output = _git(["rev-parse", "--show-toplevel"], cwd)
    root = output.strip()
    if not root:
        raise GitError("git rev-parse returned an empty repository root")
    return Path(root).resolve()


def capture_snapshot(git_root: Path) -> GitSnapshot:
    head = _git(["rev-parse", "HEAD"], git_root).strip()
    if not head:
        raise GitError("git rev-parse returned an empty HEAD hash")
    diff = _git(
        ["diff", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--"],
        git_root,
    )
    return GitSnapshot(root=git_root, head=head, diff=diff)
