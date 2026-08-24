#!/usr/bin/env python3
"""Extract and analyze MicroBench single-CPU logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from _analysis_core import (
    DEFAULT_WARMUP_SAMPLES,
    MIN_LOG_FILES,
    NUMBER,
    AnalysisConfig,
    BenchmarkRecord,
    Metric,
    find_one,
    parse_benchmark_fields,
    parse_number,
    read_log,
    run_analysis,
    run_cli,
)
from _analysis_core import build_parser as build_analysis_parser

WARMUP_SAMPLES = DEFAULT_WARMUP_SAMPLES

# Keep CPU frequency deliberately strict. In particular, this must never match
# NEMU's unrelated "simulation frequency" field.
CPU_FREQUENCY_RE = re.compile(
    rf"(?im)^\s*(?:"
    rf"Average\s+CPU(?:\s*#?\d+)?\s+frequency"
    rf"|CPU(?:\s*#?\d+)?\s+frequency"
    rf")\s*[:=]\s*({NUMBER})\s*(GHz|MHz|kHz|Hz)\b"
)


@dataclass(frozen=True)
class Record(BenchmarkRecord):
    cpu_frequency_mhz: float


def convert_frequency_to_mhz(value: float, unit: str) -> float:
    factors = {"ghz": 1000.0, "mhz": 1.0, "khz": 0.001, "hz": 0.000001}
    return value * factors[unit.lower()]


def parse_log(path: Path) -> Record:
    text = read_log(path)
    common = parse_benchmark_fields(text, path)
    frequency_value, frequency_unit = find_one(
        text, CPU_FREQUENCY_RE, "CPU Frequency", path
    )
    return Record(
        file=path,
        marks=common.marks,
        scored_time_ms=common.scored_time_ms,
        compile_flags_lines=common.compile_flags_lines,
        cpu_frequency_mhz=convert_frequency_to_mhz(
            parse_number(frequency_value), frequency_unit
        ),
    )


METRICS = (
    Metric("marks", "Marks", plot_stem="marks"),
    Metric(
        "scored_time_ms",
        "Scored Time",
        unit="ms",
        plot_stem="scored_time",
    ),
    Metric(
        "cpu_frequency_mhz",
        "CPU Frequency",
        unit="MHz",
        plot_stem="cpu_frequency",
    ),
)
CONFIG = AnalysisConfig(
    description="提取单 CPU 测试日志并生成汇总、统计和折线图。",
    metrics=METRICS,
    warmup_samples=WARMUP_SAMPLES,
    minimum_log_files=MIN_LOG_FILES,
)


def build_parser(description: str = CONFIG.description):
    return build_analysis_parser(description)


def run(input_dir: Path, output_dir: Path) -> Path:
    return run_analysis(input_dir, output_dir, parse_log, CONFIG)


def main() -> int:
    return run_cli(CONFIG, parse_log)


if __name__ == "__main__":
    raise SystemExit(main())
