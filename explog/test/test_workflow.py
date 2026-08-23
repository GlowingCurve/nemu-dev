from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from explog.errors import DirectoryError, LogError, ScriptError
from explog.log import read_log
from explog.workflow import generate_id, run_experiment


def write_config(
    path: Path,
    *,
    experiment_scripts: list[list[str]],
    processing_scripts: list[list[str]],
    data_root: str = "experiment-data",
) -> None:
    path.write_text(
        "\n".join(
            [
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
    assert (git_repo / root.data_dir / "raw").is_dir()
    assert (git_repo / root.data_dir / "processed").is_dir()
    assert [record["id"] for record in read_log(log_path)] == [root.id, child.id]


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
            "message": "message",
            "git_commit": node.git_commit,
            "git_diff": node.git_diff,
            "data_dir": "experiment-data/successful",
        }
    ]


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
    assert not marker.exists()
    assert not log_path.exists()
