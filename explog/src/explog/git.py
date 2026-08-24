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


@dataclass(frozen=True)
class RepositoryStatus:
    root: Path
    head: str
    tracked_changes: int
    untracked_files: int


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


def inspect_repository(git_root: Path) -> RepositoryStatus:
    head = _git(["rev-parse", "HEAD"], git_root).strip()
    if not head:
        raise GitError("git rev-parse returned an empty HEAD hash")

    porcelain = _git(["status", "--porcelain=v1", "--untracked-files=all"], git_root)
    lines = porcelain.splitlines()
    untracked_files = sum(line.startswith("?? ") for line in lines)
    return RepositoryStatus(
        root=git_root,
        head=head,
        tracked_changes=len(lines) - untracked_files,
        untracked_files=untracked_files,
    )


def capture_snapshot(git_root: Path) -> GitSnapshot:
    head = _git(["rev-parse", "HEAD"], git_root).strip()
    if not head:
        raise GitError("git rev-parse returned an empty HEAD hash")
    _git(["add", "-N", "--", "."], git_root)
    diff = _git(
        ["diff", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--"],
        git_root,
    )
    return GitSnapshot(root=git_root, head=head, diff=diff)


def write_diff_file(path: Path, diff: str) -> None:
    try:
        path.write_text(diff, encoding="utf-8", newline="")
    except (OSError, UnicodeError, ValueError) as error:
        raise GitError(f"cannot write Git diff {path}: {error}") from error
