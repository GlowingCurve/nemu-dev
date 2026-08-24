from pathlib import Path

from conftest import run_git

from explog.git import capture_snapshot, inspect_repository


def test_snapshot_contains_full_head_and_staged_and_unstaged_changes(
    git_repo: Path,
) -> None:
    staged = git_repo / "staged.txt"
    staged.write_text("base\n", encoding="utf-8")
    unstaged = git_repo / "unstaged.txt"
    unstaged.write_text("base\n", encoding="utf-8")
    run_git(git_repo, "add", "staged.txt", "unstaged.txt")
    run_git(git_repo, "commit", "-qm", "add fixtures")

    staged.write_text("staged final\n", encoding="utf-8")
    run_git(git_repo, "add", "staged.txt")
    unstaged.write_text("unstaged final\n", encoding="utf-8")
    (git_repo / "untracked.txt").write_text("not captured\n", encoding="utf-8")

    snapshot = capture_snapshot(git_repo)

    assert snapshot.head == run_git(git_repo, "rev-parse", "HEAD").strip()
    assert "+staged final" in snapshot.diff
    assert "+unstaged final" in snapshot.diff
    assert "untracked.txt" not in snapshot.diff
    assert "index " in snapshot.diff
    index_line = next(
        line for line in snapshot.diff.splitlines() if line.startswith("index ")
    )
    old_and_new = index_line.split()[1]
    assert all(len(value) == len(snapshot.head) for value in old_and_new.split(".."))


def test_repository_status_counts_tracked_and_untracked_changes(
    git_repo: Path,
) -> None:
    (git_repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (git_repo / "untracked.txt").write_text("new\n", encoding="utf-8")

    status = inspect_repository(git_repo)

    assert status.root == git_repo
    assert status.tracked_changes == 1
    assert status.untracked_files == 1
