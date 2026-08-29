from __future__ import annotations

from pathlib import Path

import pytest

from explog.cli import main
from explog.listing import format_nodes, list_nodes
from explog.log import append_record


def _record(
    record_id: str,
    timestamp: str,
    *,
    parent_id: str | None = None,
    message: str = "message",
) -> dict[str, object]:
    return {
        "id": record_id,
        "parent_id": parent_id,
        "timestamp": timestamp,
        "message": message,
        "git_commit": "abc123",
        "git_diff_path": f"data/{record_id}/git.diff",
        "data_dir": f"data/{record_id}",
    }


def test_list_sorts_in_utc_stably_and_formats_exact_table(tmp_path: Path) -> None:
    log_path = tmp_path / "custom.jsonl"
    append_record(
        log_path,
        _record(
            "child",
            "2026-08-24T10:00:00+02:00",
            parent_id="root",
            message="第一行\n第二行\t末尾",
        ),
    )
    append_record(log_path, _record("root", "2026-08-24T07:30:00Z"))
    append_record(log_path, _record("same", "2026-08-24T08:00:00Z"))

    nodes = list_nodes(log_path)

    assert [node.id for node in nodes] == ["root", "child", "same"]
    assert format_nodes(nodes) == (
        "TIMESTAMP                  ID     PARENT  MESSAGE\n"
        "2026-08-24T07:30:00Z       root   -       message\n"
        "2026-08-24T10:00:00+02:00  child  root    第一行\\n第二行\\t末尾\n"
        "2026-08-24T08:00:00Z       same   -       message"
    )


def test_list_empty_log_has_no_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_path = tmp_path / "empty.jsonl"
    log_path.touch()

    assert main(["list", "--log", str(log_path)]) == 0
    assert capsys.readouterr().out == ""


def test_list_uses_config_log_path_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_path = tmp_path / "custom.jsonl"
    append_record(log_path, _record("standalone", "2026-08-24T08:00:00Z"))
    (tmp_path / "explog.toml").write_text(
        "\n".join(
            [
                'log = "custom.jsonl"',
                'data_root = "experiment-data"',
                "experiment_scripts = []",
                "data_processing_scripts = []",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["list"]) == 0

    captured = capsys.readouterr()
    assert "standalone" in captured.out
    assert captured.err == ""
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "custom.jsonl",
        "explog.toml",
    ]


def test_list_missing_log_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list", "--log", str(tmp_path / "missing.jsonl")]) == 1
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("timestamp", "error_text"),
    [
        ("not-a-time", "invalid ISO 8601 timestamp"),
        ("2026-08-24T08:00:00", "without timezone"),
    ],
)
def test_list_rejects_invalid_or_naive_timestamp_with_node_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    timestamp: str,
    error_text: str,
) -> None:
    log_path = tmp_path / "bad.jsonl"
    append_record(log_path, _record("bad-time", timestamp))

    assert main(["list", "--log", str(log_path)]) == 1
    error = capsys.readouterr().err
    assert "bad-time" in error
    assert error_text in error
