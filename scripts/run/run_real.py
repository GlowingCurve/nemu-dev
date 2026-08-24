#!/usr/bin/env python3
"""Run MicroBench until its scored-time statistics stabilize."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# The runners are executable files in a subdirectory; expose shared script helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _benchmark_stability import (  # noqa: E402
    MAX_RUNS,
    MIN_RUNS,
    RMOE_THRESHOLD_PERCENT,
    WARMUP_RUNS,
    calculate_after_warmup,
    extract_scored_time_ms,
    rmoe_is_below_threshold,
    student_t_critical_99,
)
from _common import (  # noqa: E402
    ScriptError,
    main_guard,
    normalize_returncode,
    program_name,
)
from _run_config import (  # noqa: E402
    add_run_config_arguments,
    copy_compile_flags,
    make_run_command,
    resolve_run_config,
)


def append_load_average(log_file: Path) -> None:
    load_1m, load_5m, load_15m, _runnable_tasks, _last_pid = (
        Path("/proc/loadavg").read_text(encoding="utf-8").split()
    )
    current_time = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n[{current_time}] Load average after make: "
            f"1m={load_1m} 5m={load_5m} 15m={load_15m}\n"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(sys.argv[0]),
        description=(
            "Run MicroBench at least 15 and at most 125 times. Discard the "
            "first 5 valid Scored time samples and stop when the two-sided "
            "99% RMOE of the remaining samples is below 1%."
        ),
    )
    add_run_config_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = resolve_run_config(args)
    copy_compile_flags(config)

    # Check the statistics dependency before starting a potentially long run.
    student_t_critical_99(MIN_RUNS - WARMUP_RUNS)

    microbench = os.environ.get("MICROBENCH")
    if not microbench:
        print("Error: MICROBENCH is not set.", file=sys.stderr)
        return 2

    log_files = [config.output / f"log-{index}" for index in range(1, MAX_RUNS + 1)]
    existing_log = next((log_file for log_file in log_files if log_file.exists()), None)
    if existing_log is not None:
        raise ScriptError(f"Error: output log already exists: {existing_log}", 2)

    print(f"ARCH: {config.arch}")
    print(f"Runs: minimum {MIN_RUNS}, maximum {MAX_RUNS}")
    print(
        f"Stop condition: discard the first {WARMUP_RUNS} valid Scored time "
        f"samples, then require two-sided 99% RMOE < "
        f"{RMOE_THRESHOLD_PERCENT:g}%"
    )
    print(f"Logs will be saved in: {config.output}", flush=True)

    failed = 0
    attempts = 0
    scored_times_ms: list[float] = []
    converged = False
    for index, log_file in enumerate(log_files, start=1):
        attempts = index
        print(
            f"[{index}/{MAX_RUNS}] Running make ARCH={config.arch} run",
            flush=True,
        )

        with log_file.open("x", encoding="utf-8") as stream:
            try:
                result = subprocess.run(
                    make_run_command(microbench, config.arch),
                    cwd=SCRIPT_DIR,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                status = normalize_returncode(result.returncode)
            except OSError as exc:
                stream.write(f"{exc}\n")
                status = 127

        if status != 0:
            print(
                f"[{index}/{MAX_RUNS}] Failed with status {status}: {log_file}",
                file=sys.stderr,
                flush=True,
            )
            failed += 1
        else:
            try:
                scored_time_ms = extract_scored_time_ms(log_file)
            except ValueError as exc:
                print(
                    f"[{index}/{MAX_RUNS}] Invalid benchmark log: {exc}: {log_file}",
                    file=sys.stderr,
                    flush=True,
                )
                failed += 1
            else:
                scored_times_ms.append(scored_time_ms)
                print(
                    f"[{index}/{MAX_RUNS}] Finished: {log_file} "
                    f"(Scored time: {scored_time_ms:.4f} ms)",
                    flush=True,
                )

        append_load_average(log_file)

        if len(scored_times_ms) < MIN_RUNS:
            if index >= MIN_RUNS:
                print(
                    f"RMOE check pending: {len(scored_times_ms)}/{MIN_RUNS} "
                    "valid Scored time samples.",
                    flush=True,
                )
            continue

        result = calculate_after_warmup(scored_times_ms)
        print(
            f"RMOE after {len(scored_times_ms)} valid runs "
            f"(first {WARMUP_RUNS} discarded, n={result.sample_count}): "
            f"mean={result.mean_ms:.4f} ms, "
            f"99% RMOE={result.rmoe99_percent:.4f}%",
            flush=True,
        )
        if rmoe_is_below_threshold(result):
            converged = True
            break

    if failed:
        print(
            f"Completed {attempts} run attempt(s); {failed} run(s) failed or "
            "produced invalid output.",
            file=sys.stderr,
        )
        return 1

    if converged:
        print(
            f"Stopped after {attempts} runs: two-sided 99% RMOE is below "
            f"{RMOE_THRESHOLD_PERCENT:g}%."
        )
    else:
        print(
            f"Stopped at the maximum of {MAX_RUNS} runs before two-sided 99% "
            f"RMOE fell below {RMOE_THRESHOLD_PERCENT:g}%.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    main_guard(main)
