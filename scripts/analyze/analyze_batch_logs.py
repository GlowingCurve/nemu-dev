#!/usr/bin/env python3
"""Extract and analyze MicroBench batch logs."""

from __future__ import annotations

import sys
from pathlib import Path

import analyze_logs as base

BATCH_SIZE = 8
base.WARMUP_SAMPLES = BATCH_SIZE


def run(input_dir: Path, output_dir: Path) -> Path:
    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    log_paths = base.discover_logs(input_dir)
    if len(log_paths) < base.MIN_LOG_FILES:
        raise base.LogFormatError(
            f"{input_dir}: 只找到 {len(log_paths)} 个以 log 开头的日志文件，"
            f"至少需要 {base.MIN_LOG_FILES} 个"
        )

    # Validate every log before creating the output directory.
    records = [base.parse_log(path) for path in log_paths]
    nemu_variant = base.determine_nemu_variant(records)

    output_dir.mkdir(parents=True, exist_ok=True)
    base.write_summary(records, output_dir)
    base.write_statistics(
        records,
        output_dir,
        nemu_variant,
        include_cpu_frequency=True,
    )
    base.write_plots(records, output_dir, nemu_variant)
    return output_dir


def main() -> int:
    parser = base.build_parser("提取批量测试日志并生成汇总、统计和折线图。")
    args = parser.parse_args()
    try:
        output_dir = run(args.input_dir, args.output_dir)
    except (base.LogFormatError, RuntimeError, OSError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1

    print(f"处理完成，输出目录: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
