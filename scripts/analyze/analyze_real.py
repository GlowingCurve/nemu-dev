#!/usr/bin/env python3
"""Extract and analyze MicroBench system-load logs."""

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
LOAD_AVERAGE_RE = re.compile(
    rf"(?im)^\s*(?:\[[^\]\r\n]+\]\s*)?"
    rf"Load\s+average(?:\s+after\s+make)?\s*[:=]\s*"
    rf"1m\s*=\s*({NUMBER})\s+"
    rf"5m\s*=\s*({NUMBER})\s+"
    rf"15m\s*=\s*({NUMBER})\s*$"
)


@dataclass(frozen=True)
class Record(BenchmarkRecord):
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float


def parse_log(path: Path) -> Record:
    text = read_log(path)
    common = parse_benchmark_fields(text, path)
    load_1m, load_5m, load_15m = find_one(text, LOAD_AVERAGE_RE, "Load Average", path)
    return Record(
        file=path,
        marks=common.marks,
        scored_time_ms=common.scored_time_ms,
        compile_flags_lines=common.compile_flags_lines,
        load_average_1m=parse_number(load_1m),
        load_average_5m=parse_number(load_5m),
        load_average_15m=parse_number(load_15m),
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
        "load_average_1m",
        "Load Average (1m)",
        include_in_statistics=False,
    ),
    Metric(
        "load_average_5m",
        "Load Average (5m)",
        include_in_statistics=False,
    ),
    Metric(
        "load_average_15m",
        "Load Average (15m)",
        include_in_statistics=False,
    ),
)
CONFIG = AnalysisConfig(
    description="提取系统负载测试日志并生成汇总、统计和折线图。",
    metrics=METRICS,
    warmup_samples=WARMUP_SAMPLES,
    minimum_log_files=MIN_LOG_FILES,
)


def build_parser():
    return build_analysis_parser(CONFIG.description)


def run(input_dir: Path, output_dir: Path) -> Path:
    return run_analysis(input_dir, output_dir, parse_log, CONFIG)


def main() -> int:
    return run_cli(CONFIG, parse_log)


if __name__ == "__main__":
    raise SystemExit(main())
