#!/usr/bin/env python3
"""Extract and analyze MicroBench single-CPU logs."""

from __future__ import annotations

import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from _analysis_core import (
    DEFAULT_WARMUP_SAMPLES,
    MIN_LOG_FILES,
    NUMBER,
    AnalysisConfig,
    BenchmarkRecord,
    LogFormatError,
    Metric,
    find_one,
    format_number,
    parse_benchmark_fields,
    parse_number,
    read_log,
    run_analysis,
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
PERF_STAT_RE = re.compile(
    r"(?m)^\s*([^;\r\n]+?)\s*;\s*[^;\r\n]*;\s*"
    r"(instructions|cycles|branches|branch-misses):u\s*;"
)
PERF_EVENT_ATTRIBUTES = {
    "instructions": "instructions",
    "cycles": "cycles",
    "branches": "branches",
    "branch-misses": "branch_misses",
}


@dataclass(frozen=True)
class Record(BenchmarkRecord):
    cpu_frequency_mhz: float
    instructions: float | None
    cycles: float | None
    branches: float | None
    branch_misses: float | None


def convert_frequency_to_mhz(value: float, unit: str) -> float:
    factors = {"ghz": 1000.0, "mhz": 1.0, "khz": 0.001, "hz": 0.000001}
    return value * factors[unit.lower()]


def parse_perf_counts(text: str, path: Path) -> dict[str, float] | None:
    matches = PERF_STAT_RE.findall(text)
    if not matches:
        return None

    counts: dict[str, float] = {}
    for raw_value, event in matches:
        if event in counts:
            raise LogFormatError(f"{path}: 找到多个 perf 事件 {event}:u")

        value = raw_value.strip()
        if re.fullmatch(NUMBER, value) is None:
            raise LogFormatError(f"{path}: perf 事件 {event}:u 没有有效计数")
        counts[event] = parse_number(value)

    missing = [event for event in PERF_EVENT_ATTRIBUTES if event not in counts]
    if missing:
        missing_names = ", ".join(f"{event}:u" for event in missing)
        raise LogFormatError(f"{path}: 缺少 perf 事件: {missing_names}")
    return counts


def parse_log(path: Path) -> Record:
    text = read_log(path)
    common = parse_benchmark_fields(text, path)
    frequency_value, frequency_unit = find_one(
        text, CPU_FREQUENCY_RE, "CPU Frequency", path
    )
    perf_counts = parse_perf_counts(text, path)
    return Record(
        file=path,
        marks=common.marks,
        scored_time_ms=common.scored_time_ms,
        compile_flags_lines=common.compile_flags_lines,
        cpu_frequency_mhz=convert_frequency_to_mhz(
            parse_number(frequency_value), frequency_unit
        ),
        instructions=None if perf_counts is None else perf_counts["instructions"],
        cycles=None if perf_counts is None else perf_counts["cycles"],
        branches=None if perf_counts is None else perf_counts["branches"],
        branch_misses=None if perf_counts is None else perf_counts["branch-misses"],
    )


def parse_single_log(path: Path) -> Record:
    record = parse_log(path)
    missing = [
        event
        for event, attribute in PERF_EVENT_ATTRIBUTES.items()
        if getattr(record, attribute) is None
    ]
    if missing:
        events = ", ".join(f"{event}:u" for event in missing)
        raise LogFormatError(f"{path}: 未找到 perf stat 用户态事件: {events}")
    return record


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
PERF_METRICS = (
    Metric("instructions", "Inst"),
    Metric("cycles", "Cycles"),
    Metric("branches", "Branch"),
    Metric("branch_misses", "Branch Miss"),
)
CONFIG = AnalysisConfig(
    description="提取单 CPU 测试日志并生成汇总、统计和折线图。",
    metrics=METRICS,
    warmup_samples=WARMUP_SAMPLES,
    minimum_log_files=MIN_LOG_FILES,
)


def build_parser(description: str = CONFIG.description):
    return build_analysis_parser(description)


def append_perf_averages(report: Path, records: list[Record]) -> None:
    warmed_records = records[WARMUP_SAMPLES:]
    lines = [
        "",
        "性能计数器平均值",
        f"指标|全部样本均值|去掉前 {WARMUP_SAMPLES} 个样本后的均值",
    ]
    for metric in PERF_METRICS:
        all_values = [float(getattr(record, metric.attribute)) for record in records]
        warmed_values = [
            float(getattr(record, metric.attribute)) for record in warmed_records
        ]
        lines.append(
            "|".join(
                (
                    metric.name,
                    format_number(statistics.fmean(all_values)),
                    format_number(statistics.fmean(warmed_values)),
                )
            )
        )
    lines.append("说明：以上数值为 perf stat 用户态原始事件计数的算术平均数。")

    with report.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def run(input_dir: Path, output_dir: Path) -> Path:
    records: list[Record] = []

    def collect_record(path: Path) -> Record:
        record = parse_single_log(path)
        records.append(record)
        return record

    result_dir = run_analysis(input_dir, output_dir, collect_record, CONFIG)
    append_perf_averages(result_dir / "stat" / "statistics.txt", records)
    return result_dir


def main() -> int:
    args = build_parser().parse_args()
    try:
        output_dir = run(args.input_dir, args.output_dir)
    except (LogFormatError, RuntimeError, OSError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1

    print(f"处理完成，输出目录: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
