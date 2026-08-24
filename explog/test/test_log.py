from pathlib import Path

import pytest

from explog.errors import LogError
from explog.log import append_record, read_log, read_nodes
from explog.model import ExperimentNode


def test_append_and_read_compact_jsonl_with_special_characters(tmp_path: Path) -> None:
    log_path = tmp_path / "experiments.jsonl"
    first = {
        "id": "root",
        "message": 'line one\nline two: "你好" \\ end',
        "parent_id": None,
    }
    second = {"id": "child", "message": "tab\there", "parent_id": "root"}

    append_record(log_path, first)
    append_record(log_path, second)

    physical_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(physical_lines) == 2
    assert "\\n" in physical_lines[0]
    assert "你好" in physical_lines[0]
    assert '"id": ' not in physical_lines[0]
    assert read_log(log_path) == [first, second]


def test_read_missing_log_is_empty(tmp_path: Path) -> None:
    assert read_log(tmp_path / "missing.jsonl") == []


def test_read_missing_log_can_be_an_error(tmp_path: Path) -> None:
    with pytest.raises(LogError, match="does not exist"):
        read_log(tmp_path / "missing.jsonl", missing_ok=False)


def test_reject_broken_log_symlink(tmp_path: Path) -> None:
    log_path = tmp_path / "broken.jsonl"
    log_path.symlink_to(tmp_path / "missing.jsonl")

    with pytest.raises(LogError, match="broken symbolic link"):
        read_log(log_path)


@pytest.mark.parametrize("content", ["\n", "not json\n", "[]\n", '{"x":1}\n'])
def test_reject_invalid_log(tmp_path: Path, content: str) -> None:
    log_path = tmp_path / "bad.jsonl"
    log_path.write_text(content, encoding="utf-8")

    with pytest.raises(LogError):
        read_log(log_path)


def test_reject_duplicate_ids_in_existing_log(tmp_path: Path) -> None:
    log_path = tmp_path / "bad.jsonl"
    log_path.write_text('{"id":"same"}\n{"id":"same"}\n', encoding="utf-8")

    with pytest.raises(LogError, match="duplicate id"):
        read_log(log_path)


def _complete_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "id": "node-1",
        "parent_id": None,
        "timestamp": "2026-08-24T12:34:56Z",
        "message": "message",
        "git_commit": "abc123",
        "git_diff_path": "data/node-1/git.diff",
        "data_dir": "data/node-1",
    }
    record.update(overrides)
    return record


def test_read_nodes_validates_and_ignores_extra_fields(tmp_path: Path) -> None:
    log_path = tmp_path / "experiments.jsonl"
    append_record(log_path, _complete_record(extra={"future": True}))

    assert read_nodes(log_path) == [
        ExperimentNode(
            id="node-1",
            parent_id=None,
            timestamp="2026-08-24T12:34:56Z",
            message="message",
            git_commit="abc123",
            git_diff_path="data/node-1/git.diff",
            data_dir="data/node-1",
        )
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("parent_id", 1),
        ("timestamp", None),
        ("message", ["not", "a", "string"]),
        ("git_commit", 123),
        ("git_diff_path", None),
        ("data_dir", {}),
    ],
)
def test_read_nodes_rejects_wrong_field_types_with_node_id(
    tmp_path: Path, field: str, value: object
) -> None:
    log_path = tmp_path / "bad.jsonl"
    append_record(log_path, _complete_record(**{field: value}))

    with pytest.raises(LogError, match="node-1"):
        read_nodes(log_path)


@pytest.mark.parametrize(
    "field",
    ["parent_id", "timestamp", "message", "git_commit", "git_diff_path", "data_dir"],
)
def test_read_nodes_rejects_missing_fields_with_node_id(
    tmp_path: Path, field: str
) -> None:
    log_path = tmp_path / "bad.jsonl"
    record = _complete_record()
    del record[field]
    append_record(log_path, record)

    with pytest.raises(LogError, match="node-1"):
        read_nodes(log_path)
