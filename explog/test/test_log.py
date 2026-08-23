from pathlib import Path

import pytest

from explog.errors import LogError
from explog.log import append_record, read_log


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
