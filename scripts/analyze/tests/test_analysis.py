from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ANALYZE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANALYZE_DIR))

import _analysis_core as core
import analyze_batch_logs as batch
import analyze_logs as single
import analyze_system_logs as system
import pytest


def write_log(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_single_log_parser_normalizes_units(tmp_path: Path) -> None:
    log = tmp_path / "log-1"
    write_log(
        log,
        "MicroBench finished with 1,234.5 Marks",
        "Scored time: 2 s",
        "Average CPU7 frequency: 4 GHz",
        "Compile Flags: -O2",
    )

    record = single.parse_log(log)

    assert record.marks == 1234.5
    assert record.scored_time_ms == 2000.0
    assert record.cpu_frequency_mhz == 4000.0
    assert record.compile_flags_lines == ("Compile Flags: -O2",)


def test_system_log_parser_extracts_load_average(tmp_path: Path) -> None:
    log = tmp_path / "log-1"
    write_log(
        log,
        "Marks = 900",
        "Scored time = 2500 us",
        "[2026-08-24 12:00:00] Load average after make: 1m=0.25 5m=0.5 15m=1.0",
    )

    record = system.parse_log(log)

    assert record.scored_time_ms == 2.5
    assert (
        record.load_average_1m,
        record.load_average_5m,
        record.load_average_15m,
    ) == (0.25, 0.5, 1.0)


def test_batch_config_does_not_mutate_single_config() -> None:
    assert single.CONFIG.warmup_samples == 5
    assert batch.CONFIG.warmup_samples == 8


def test_pipeline_writes_configured_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    write_log(
        input_dir / "log-1",
        "Marks: 100",
        "Scored time: 10 ms",
        "CPU frequency: 4,000 MHz",
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    config = replace(single.CONFIG, minimum_log_files=1, warmup_samples=0)
    monkeypatch.setattr(core, "write_plots", lambda *_args: None)

    result = core.run_analysis(input_dir, output_dir, single.parse_log, config)

    assert result == output_dir.resolve()
    assert (output_dir / "stat" / "summary.txt").read_text(encoding="utf-8") == (
        "序号|Marks|Scored Time|CPU Frequency\n1|100|10 ms|4000 MHz\n"
    )
    statistics_text = (output_dir / "stat" / "statistics.txt").read_text(
        encoding="utf-8"
    )
    assert statistics_text.startswith("Original NEMU\n\n全部样本\n")
    assert "CPU Frequency (MHz)|1|4000|N/A|4000|N/A|N/A" in statistics_text


def test_pipeline_requires_existing_output_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    write_log(
        input_dir / "log-1",
        "Marks: 100",
        "Scored time: 10 ms",
        "CPU frequency: 4000 MHz",
    )
    output_dir = tmp_path / "output"
    config = replace(single.CONFIG, minimum_log_files=1)

    with pytest.raises(core.LogFormatError, match="输出目录不存在"):
        core.run_analysis(input_dir, output_dir, single.parse_log, config)

    assert not output_dir.exists()


def test_single_pipeline_generates_all_artifacts(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for index in range(1, single.MIN_LOG_FILES + 1):
        write_log(
            input_dir / f"log-{index}",
            f"Marks: {100 + index}",
            f"Scored time: {10 + index / 10} ms",
            f"CPU frequency: {4000 + index} MHz",
        )

    output_root = tmp_path / "output"
    output_root.mkdir()
    output_dir = single.run(input_dir, output_root)

    assert {path.name for path in output_dir.iterdir()} == {"stat", "plot"}
    assert {path.name for path in (output_dir / "stat").iterdir()} == {
        "summary.txt",
        "statistics.txt",
    }
    assert {path.name for path in (output_dir / "plot").iterdir()} == {
        "marks_raw.png",
        "marks.png",
        "scored_time_raw.png",
        "scored_time.png",
        "cpu_frequency_raw.png",
        "cpu_frequency.png",
    }
    assert "去掉前 5 个样本" in (output_dir / "stat" / "statistics.txt").read_text(
        encoding="utf-8"
    )
