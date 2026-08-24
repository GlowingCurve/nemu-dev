#!/usr/bin/env python3
"""Extract and analyze MicroBench batch logs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import analyze_logs as single
from _analysis_core import run_analysis, run_cli

BATCH_SIZE = 8
CONFIG = replace(
    single.CONFIG,
    description="提取批量测试日志并生成汇总、统计和折线图。",
    warmup_samples=BATCH_SIZE,
)


def run(input_dir: Path, output_dir: Path) -> Path:
    return run_analysis(input_dir, output_dir, single.parse_log, CONFIG)


def main() -> int:
    return run_cli(CONFIG, single.parse_log)


if __name__ == "__main__":
    raise SystemExit(main())
