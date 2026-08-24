#!/usr/bin/env python3
"""Extract and analyze MicroBench system-load logs."""

from __future__ import annotations

import argparse
import math
import os
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MIN_LOG_FILES = 15
WARMUP_SAMPLES = 5

MARKS_PATTERNS = (
    re.compile(rf"(?im)^.*?\bMicroBench\b.*?\b({NUMBER})\s+Marks\b"),
    re.compile(rf"(?im)^\s*Marks\s*[:=]\s*({NUMBER})\b"),
)
SCORED_TIME_RE = re.compile(
    rf"(?im)^\s*Scored\s+time\s*[:=]\s*({NUMBER})\s*(ms|us|µs|s)\b"
)
LOAD_AVERAGE_RE = re.compile(
    rf"(?im)^\s*(?:\[[^\]\r\n]+\]\s*)?"
    rf"Load\s+average(?:\s+after\s+make)?\s*[:=]\s*"
    rf"1m\s*=\s*({NUMBER})\s+"
    rf"5m\s*=\s*({NUMBER})\s+"
    rf"15m\s*=\s*({NUMBER})\s*$"
)
COMPILE_FLAGS_RE = re.compile(r"(?i)\bCompile\s+Flags\b")


class LogFormatError(ValueError):
    """Raised when an input path or a required log field is invalid."""


@dataclass(frozen=True)
class Record:
    file: Path
    marks: float
    scored_time_ms: float
    load_average_1m: float
    load_average_5m: float
    load_average_15m: float
    compile_flags_lines: tuple[str, ...]


@dataclass(frozen=True)
class StatisticsResult:
    count: int
    mean: float
    sample_stddev: float | None
    median: float
    coefficient_of_variation: float | None
    ci95: tuple[float, float] | None
    ci99: tuple[float, float] | None


def parse_number(value: str) -> float:
    return float(value.replace(",", ""))


def find_one(
    text: str, pattern: re.Pattern[str], field: str, path: Path
) -> tuple[str, ...]:
    matches = pattern.findall(text)
    if not matches:
        raise LogFormatError(f"{path}: 未找到 {field}")
    if len(matches) > 1:
        raise LogFormatError(f"{path}: 找到多个 {field}，无法确定应使用哪一个")

    match = matches[0]
    return match if isinstance(match, tuple) else (match,)


def find_marks(text: str, path: Path) -> float:
    for pattern in MARKS_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            if len(matches) > 1:
                raise LogFormatError(
                    f"{path}: 找到多个 Marks，无法确定应使用哪一个"
                )
            return parse_number(matches[0])
    raise LogFormatError(f"{path}: 未找到 Marks")


def convert_time_to_ms(value: float, unit: str) -> float:
    factors = {"s": 1000.0, "ms": 1.0, "us": 0.001, "µs": 0.001}
    return value * factors[unit.lower()]


def parse_log(path: Path) -> Record:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise LogFormatError(f"无法读取 {path}: {error}") from error

    marks = find_marks(text, path)
    scored_value, scored_unit = find_one(
        text, SCORED_TIME_RE, "Scored Time", path
    )
    load_1m, load_5m, load_15m = find_one(
        text, LOAD_AVERAGE_RE, "Load Average", path
    )

    return Record(
        file=path,
        marks=marks,
        scored_time_ms=convert_time_to_ms(
            parse_number(scored_value), scored_unit
        ),
        load_average_1m=parse_number(load_1m),
        load_average_5m=parse_number(load_5m),
        load_average_15m=parse_number(load_15m),
        compile_flags_lines=tuple(
            line for line in text.splitlines() if COMPILE_FLAGS_RE.search(line)
        ),
    )


def natural_key(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.name.casefold())
    return [int(part) if part.isdigit() else part for part in parts]


def discover_logs(source_dir: Path) -> list[Path]:
    try:
        paths = [
            path
            for path in source_dir.iterdir()
            if path.is_file() and path.name.startswith("log")
        ]
    except OSError as error:
        raise LogFormatError(f"无法遍历目录 {source_dir}: {error}") from error

    return sorted(paths, key=natural_key)


def determine_nemu_variant(records: Sequence[Record]) -> str:
    records_with_flags = [
        record for record in records if record.compile_flags_lines]
    if not records_with_flags:
        return "Original NEMU"

    records_without_flags = [
        record.file.name for record in records if not record.compile_flags_lines
    ]
    if records_without_flags:
        raise LogFormatError(
            "检测到 Compile Flags 后，要求所有日志都包含该字段；缺少字段的日志: "
            + ", ".join(records_without_flags)
        )

    expected_line = records[0].compile_flags_lines[0]
    for record in records:
        if any(line != expected_line for line in record.compile_flags_lines):
            raise LogFormatError(
                f"{record.file}: Compile Flags 所在行与其他日志不完全相同"
            )

    return "NEMU Develop"


def calculate_statistics(values: Sequence[float]) -> StatisticsResult:
    count = len(values)
    mean = statistics.fmean(values)
    median = statistics.median(values)

    if count < 2:
        return StatisticsResult(count, mean, None, median, None, None, None)

    sample_stddev = statistics.stdev(values)
    coefficient = None if mean == 0 else sample_stddev / abs(mean) * 100.0

    try:
        from scipy.stats import t
    except ImportError as error:
        raise RuntimeError(
            "缺少 scipy，无法计算 Student's t 置信区间；请执行 "
            "python3 -m pip install -r requirements.txt"
        ) from error

    standard_error = sample_stddev / math.sqrt(count)
    ci95_margin = float(t.ppf(0.975, count - 1)) * standard_error
    ci99_margin = float(t.ppf(0.995, count - 1)) * standard_error
    return StatisticsResult(
        count=count,
        mean=mean,
        sample_stddev=sample_stddev,
        median=median,
        coefficient_of_variation=coefficient,
        ci95=(mean - ci95_margin, mean + ci95_margin),
        ci99=(mean - ci99_margin, mean + ci99_margin),
    )


def format_number(value: float) -> str:
    return f"{value:.10g}"


def format_optional(value: float | None) -> str:
    return "N/A" if value is None else format_number(value)


def format_ci(interval: tuple[float, float] | None) -> str:
    if interval is None:
        return "N/A"
    return f"[{format_number(interval[0])}, {format_number(interval[1])}]"


def confidence_half_width(
    mean: float, interval: tuple[float, float] | None
) -> float | None:
    if interval is None:
        return None
    return interval[1] - mean


def relative_margin_of_error(
    mean: float, interval: tuple[float, float] | None
) -> float | None:
    half_width = confidence_half_width(mean, interval)
    if half_width is None or mean == 0:
        return None
    return half_width / abs(mean) * 100.0


def write_summary(records: Sequence[Record], output_dir: Path) -> None:
    lines = [
        "序号|Marks|Scored Time|Load Average (1m)|"
        "Load Average (5m)|Load Average (15m)"
    ]
    for index, record in enumerate(records, start=1):
        lines.append(
            "|".join(
                (
                    str(index),
                    format_number(record.marks),
                    f"{format_number(record.scored_time_ms)} ms",
                    format_number(record.load_average_1m),
                    format_number(record.load_average_5m),
                    format_number(record.load_average_15m),
                )
            )
        )
    (output_dir / "summary.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def statistics_rows(
    records: Sequence[Record],
) -> tuple[tuple[str, StatisticsResult], ...]:
    return (
        (
            "Marks",
            calculate_statistics([record.marks for record in records]),
        ),
        (
            "Scored Time (ms)",
            calculate_statistics(
                [record.scored_time_ms for record in records]
            ),
        ),
    )


def append_statistics_section(
    lines: list[str], title: str, records: Sequence[Record]
) -> None:
    lines.extend(
        (
            title,
            "指标|样本数|均值|样本标准差|中位数|变异系数 (%)|"
            "95% CI|95% 半宽|95% RMOE (%)|99% CI|99% 半宽|99% RMOE (%)",
        )
    )
    for name, result in statistics_rows(records):
        lines.append(
            "|".join(
                (
                    name,
                    str(result.count),
                    format_number(result.mean),
                    format_optional(result.sample_stddev),
                    format_number(result.median),
                    format_optional(result.coefficient_of_variation),
                    format_ci(result.ci95),
                    format_optional(
                        confidence_half_width(result.mean, result.ci95)
                    ),
                    format_optional(
                        relative_margin_of_error(result.mean, result.ci95)
                    ),
                    format_ci(result.ci99),
                    format_optional(
                        confidence_half_width(result.mean, result.ci99)
                    ),
                    format_optional(
                        relative_margin_of_error(result.mean, result.ci99)
                    ),
                )
            )
        )


def write_statistics(
    records: Sequence[Record], output_dir: Path, nemu_variant: str
) -> None:
    lines = [nemu_variant, ""]
    append_statistics_section(lines, "全部样本", records)
    lines.append("")
    append_statistics_section(
        lines,
        f"去掉前 {WARMUP_SAMPLES} 个样本",
        records[WARMUP_SAMPLES:],
    )
    lines.extend(
        (
            "",
            "说明：标准差为样本标准差（n-1）；变异系数 = 样本标准差 / |均值| × 100%。",
            "置信区间为基于 Student's t 分布的总体均值双侧置信区间。",
            "半宽 = 置信区间上限 - 均值；RMOE = 半宽 / |均值| × 100%。",
            "样本数小于 2 时，样本标准差、变异系数、置信区间、半宽和 RMOE 记为 N/A。",
        )
    )
    (output_dir / "statistics.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def plot_series(
    x_values: Iterable[int],
    y_values: Sequence[float],
    ylabel: str,
    title: str,
    nemu_variant: str,
    output_path: Path,
) -> None:
    cache_dir = Path(tempfile.gettempdir()) / \
        f"nemu-log-analyzer-mpl-{os.getuid()}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))
    os.environ.setdefault("MPLBACKEND", "Agg")

    try:
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MaxNLocator
    except ImportError as error:
        raise RuntimeError(
            "缺少 matplotlib，无法生成图片；请执行 "
            "python3 -m pip install -r requirements.txt"
        ) from error

    stats = calculate_statistics(y_values)

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 11,
            "axes.linewidth": 1.0,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    figure, axes = plt.subplots(figsize=(10, 5.5))
    axes.plot(
        list(x_values),
        y_values,
        marker="o",
        markersize=3.5,
        linewidth=1.2,
        color="#1f77b4",
        label="Samples",
    )
    axes.axhline(
        stats.mean,
        color="red",
        linewidth=1.4,
        linestyle="--",
        label=f"Mean = {format_number(stats.mean)}",
    )
    axes.set_xlabel("Sequence")
    axes.set_ylabel(ylabel)
    axes.set_title(
        f"{title} (by {nemu_variant} @4GHz)", fontsize=12, pad=10
    )
    axes.grid(True, linestyle="--", linewidth=0.6, alpha=0.4)
    axes.margins(x=0.02)
    axes.xaxis.set_major_locator(MaxNLocator(integer=True))

    axes.legend(
        loc="lower right",
        frameon=True,
        framealpha=0.9,
        edgecolor="#cccccc",
        fontsize=9,
    )

    figure.tight_layout()
    figure.savefig(output_path, dpi=300)
    plt.close(figure)


def write_plots(
    records: Sequence[Record], output_dir: Path, nemu_variant: str
) -> None:
    sequence = list(range(1, len(records) + 1))
    plot_series(
        sequence,
        [record.marks for record in records],
        "Marks",
        "Marks ",
        nemu_variant,
        output_dir / "marks_raw.png",
    )
    plot_series(
        sequence,
        [record.scored_time_ms for record in records],
        "Scored Time (ms)",
        "Scored Time ",
        nemu_variant,
        output_dir / "scored_time_raw.png",
    )

    trimmed_records = records[WARMUP_SAMPLES:]
    trimmed_sequence = list(range(1, len(trimmed_records) + 1))
    plot_series(
        trimmed_sequence,
        [record.marks for record in trimmed_records],
        "Marks",
        "Marks ",
        nemu_variant,
        output_dir / "marks.png",
    )
    plot_series(
        trimmed_sequence,
        [record.scored_time_ms for record in trimmed_records],
        "Scored Time (ms)",
        "Scored Time",
        nemu_variant,
        output_dir / "scored_time.png",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="提取系统负载测试日志并生成汇总、统计和折线图。",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--input",
        dest="input_dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="包含 log* 文件的输入目录",
    )
    parser.add_argument(
        "--output",
        dest="output_dir",
        type=Path,
        required=True,
        metavar="DIR",
        help="汇总、统计和折线图的输出目录",
    )
    return parser


def run(input_dir: Path, output_dir: Path) -> Path:
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    log_paths = discover_logs(input_dir)
    if len(log_paths) < MIN_LOG_FILES:
        raise LogFormatError(
            f"{input_dir}: 只找到 {len(log_paths)} 个以 log 开头的日志文件，"
            f"至少需要 {MIN_LOG_FILES} 个"
        )

    # Validate every log before creating the output directory.
    records = [parse_log(path) for path in log_paths]
    nemu_variant = determine_nemu_variant(records)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_summary(records, output_dir)
    write_statistics(records, output_dir, nemu_variant)
    write_plots(records, output_dir, nemu_variant)
    return output_dir


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        output_dir = run(args.input_dir, args.output_dir)
    except (LogFormatError, RuntimeError, OSError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1

    print(f"处理完成，输出目录: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
