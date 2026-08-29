from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import run_git

from explog.errors import DirectoryError, GitError, LogError, ScriptError
from explog.log import read_log
from explog.workflow import generate_id, run_experiment


def write_config(
    path: Path,
    *,
    experiment_scripts: list[list[str]],
    processing_scripts: list[list[str]],
    data_root: str = "experiment-data",
    log: str = "experiments.jsonl",
) -> None:
    path.write_text(
        "\n".join(
            [
                f"log = {json.dumps(log)}",
                f"data_root = {json.dumps(data_root)}",
                f"experiment_scripts = {json.dumps(experiment_scripts)}",
                f"data_processing_scripts = {json.dumps(processing_scripts)}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def make_script(repository: Path, name: str, body: str) -> Path:
    script = repository / name
    script.write_text(body, encoding="utf-8")
    return script


def run_empty(
    git_repo: Path,
    config_file: Path,
    log_path: Path,
    experiment_id: str,
    *,
    parent_id: str | None = None,
    message: str = "message",
):
    return run_experiment(
        config_path=config_file,
        log_path=log_path,
        message=message,
        parent_id=parent_id,
        experiment_id=experiment_id,
        cwd=git_repo,
    )


def test_generate_id_is_utc_second_timestamp() -> None:
    assert generate_id(0) == "19700101T000000Z"
    assert generate_id(1) == "19700101T000001Z"
    assert re.fullmatch(r"\d{8}T\d{6}Z", generate_id())


def test_custom_id_parent_and_relative_posix_data_dir(
    git_repo: Path, config_file: Path
) -> None:
    log_path = git_repo / "experiments.jsonl"
    root = run_empty(
        git_repo,
        config_file,
        log_path,
        "root α + #",
        message="root\nmessage",
    )
    child = run_empty(
        git_repo,
        config_file,
        log_path,
        "child",
        parent_id=root.id,
    )

    assert root.id == "root α + #"
    assert child.parent_id == root.id
    assert root.data_dir == "experiment-data/root α + #"
    assert root.git_diff_path == "experiment-data/root α + #/git.diff"
    assert (git_repo / root.data_dir / "raw").is_dir()
    assert (git_repo / root.data_dir / "processed").is_dir()
    assert (git_repo / root.git_diff_path).is_file()
    assert [record["id"] for record in read_log(log_path)] == [root.id, child.id]


def test_node_creation_timestamp_is_logged_in_utc(
    git_repo: Path, config_file: Path
) -> None:
    log_path = git_repo / "experiments.jsonl"
    before = datetime.now(UTC)

    node = run_empty(git_repo, config_file, log_path, "timestamped")

    after = datetime.now(UTC)
    timestamp = datetime.fromisoformat(node.timestamp)
    assert node.timestamp.endswith("Z")
    assert before <= timestamp <= after
    assert read_log(log_path)[0]["timestamp"] == node.timestamp


@pytest.mark.parametrize("bad_id", ["", ".", "..", "a/b", "a\\b", "bad\nname"])
def test_reject_unsafe_custom_id(
    git_repo: Path, config_file: Path, bad_id: str
) -> None:
    with pytest.raises(DirectoryError, match="single-directory"):
        run_empty(git_repo, config_file, git_repo / "log.jsonl", bad_id)

    assert not (git_repo / "log.jsonl").exists()
    assert not (git_repo / "experiment-data").exists()


def test_reject_duplicate_id_without_creating_another_directory(
    git_repo: Path, config_file: Path
) -> None:
    log_path = git_repo / "log.jsonl"
    run_empty(git_repo, config_file, log_path, "same")

    with pytest.raises(LogError, match="already exists"):
        run_empty(git_repo, config_file, log_path, "same")

    assert len(read_log(log_path)) == 1


def test_reject_missing_parent_before_writes(git_repo: Path, config_file: Path) -> None:
    log_path = git_repo / "log.jsonl"

    with pytest.raises(LogError, match="parent id does not exist"):
        run_empty(
            git_repo,
            config_file,
            log_path,
            "child",
            parent_id="missing",
        )

    assert not log_path.exists()
    assert not (git_repo / "experiment-data").exists()


def test_reject_directory_conflict_without_log_write(
    git_repo: Path, config_file: Path
) -> None:
    conflict = git_repo / "experiment-data" / "run"
    conflict.mkdir(parents=True)
    marker = conflict / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(DirectoryError, match="already exists"):
        run_empty(git_repo, config_file, git_repo / "log.jsonl", "run")

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (git_repo / "log.jsonl").exists()


def test_reject_data_root_outside_git_repository(
    git_repo: Path, config_file: Path
) -> None:
    write_config(
        config_file,
        experiment_scripts=[],
        processing_scripts=[],
        data_root="../outside",
    )

    with pytest.raises(DirectoryError, match="inside Git root"):
        run_empty(git_repo, config_file, git_repo / "log.jsonl", "run")


def test_all_scripts_run_in_order_with_expected_arguments(git_repo: Path) -> None:
    recorder = make_script(
        git_repo,
        "record.py",
        """\
import json
import pathlib
import sys

record_file = pathlib.Path(sys.argv[1])
with record_file.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sys.argv[2:]) + "\\n")
""",
    )
    calls = git_repo / "calls.jsonl"
    config = git_repo / "explog.toml"
    python = sys.executable
    write_config(
        config,
        experiment_scripts=[
            [python, str(recorder), str(calls), "experiment-1"],
            [python, str(recorder), str(calls), "experiment-2"],
        ],
        processing_scripts=[
            [python, str(recorder), str(calls), "processing-1"],
            [python, str(recorder), str(calls), "processing-2"],
        ],
    )

    node = run_empty(git_repo, config, git_repo / "log.jsonl", "successful")

    raw = str(git_repo / "experiment-data" / "successful" / "raw")
    processed = str(git_repo / "experiment-data" / "successful" / "processed")
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert recorded == [
        ["experiment-1", "--output", raw],
        ["experiment-2", "--output", raw],
        ["processing-1", "--input", raw, "--output", processed],
        ["processing-2", "--input", raw, "--output", processed],
    ]
    assert read_log(git_repo / "log.jsonl") == [
        {
            "id": "successful",
            "parent_id": None,
            "timestamp": node.timestamp,
            "message": "message",
            "git_commit": node.git_commit,
            "git_diff_path": "experiment-data/successful/git.diff",
            "data_dir": "experiment-data/successful",
        }
    ]


def test_git_diff_is_written_to_experiment_directory_and_logged(
    git_repo: Path, config_file: Path
) -> None:
    (git_repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (git_repo / "untracked.txt").write_text("new file\n", encoding="utf-8")
    log_path = git_repo / "log.jsonl"

    node = run_empty(git_repo, config_file, log_path, "with-diff")

    assert node.git_diff_path == "experiment-data/with-diff/git.diff"
    diff = (git_repo / node.git_diff_path).read_text(encoding="utf-8")
    assert "+changed" in diff
    assert "untracked.txt" in diff
    assert "+new file" in diff
    record = read_log(log_path)[0]
    assert record["git_diff_path"] == node.git_diff_path
    assert "git_diff" not in record


def test_clean_worktree_writes_empty_git_diff(
    git_repo: Path, config_file: Path
) -> None:
    run_git(git_repo, "add", config_file.name)
    run_git(git_repo, "commit", "-qm", "add config")

    node = run_empty(git_repo, config_file, git_repo / "log.jsonl", "clean")

    assert (git_repo / node.git_diff_path).read_bytes() == b""


def test_log_path_defaults_to_config_log(
    git_repo: Path, config_file: Path
) -> None:
    node = run_experiment(
        config_path=config_file,
        message="message",
        experiment_id="default-log",
        cwd=git_repo,
    )

    assert node.id == "default-log"
    assert [record["id"] for record in read_log(git_repo / "experiments.jsonl")] == [
        "default-log"
    ]


def test_diff_write_failure_keeps_directory_and_does_not_run_scripts_or_log(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = git_repo / "should-not-run"
    mark = make_script(
        git_repo,
        "mark.py",
        "import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\n",
    )
    config = git_repo / "explog.toml"
    write_config(
        config,
        experiment_scripts=[[sys.executable, str(mark), str(marker)]],
        processing_scripts=[],
    )

    def fail_write(_path: Path, _diff: str) -> None:
        raise GitError("cannot write Git diff")

    monkeypatch.setattr("explog.workflow.write_diff_file", fail_write)
    log_path = git_repo / "log.jsonl"

    with pytest.raises(GitError, match="cannot write Git diff"):
        run_empty(git_repo, config, log_path, "failed-write")

    assert (git_repo / "experiment-data" / "failed-write").is_dir()
    assert not marker.exists()
    assert not log_path.exists()


@pytest.mark.parametrize("failure_stage", ["experiment", "processing"])
def test_script_failure_keeps_data_and_does_not_write_log(
    git_repo: Path, failure_stage: str
) -> None:
    fail = make_script(git_repo, "fail.py", "raise SystemExit(7)\n")
    marker = git_repo / "should-not-run"
    mark = make_script(
        git_repo,
        "mark.py",
        "import pathlib, sys\npathlib.Path(sys.argv[1]).touch()\n",
    )
    command_fail = [sys.executable, str(fail)]
    command_mark = [sys.executable, str(mark), str(marker)]
    if failure_stage == "experiment":
        experiments = [command_fail, command_mark]
        processing = [command_mark]
    else:
        experiments = []
        processing = [command_fail, command_mark]

    config = git_repo / "explog.toml"
    write_config(
        config,
        experiment_scripts=experiments,
        processing_scripts=processing,
    )
    log_path = git_repo / "log.jsonl"

    with pytest.raises(ScriptError, match="exit status 7"):
        run_empty(git_repo, config, log_path, "failed")

    assert (git_repo / "experiment-data" / "failed").is_dir()
    assert (git_repo / "experiment-data" / "failed" / "git.diff").is_file()
    assert not marker.exists()
    assert not log_path.exists()
