#!/usr/bin/env python3
"""Run MicroBench on one CPU until its scored-time statistics stabilize."""

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
    NEMU_CGROUP,
    ScriptError,
    average_frequency_mhz,
    command_exists,
    main_guard,
    max_cpu_id,
    normalize_returncode,
    parse_cpu_list,
    program_name,
    read_text,
    sample_frequency,
)
from _run_config import (  # noqa: E402
    add_run_config_arguments,
    copy_compile_flags,
    make_run_command,
    resolve_run_config,
)

FREQ_SAMPLE_INTERVAL_SECONDS = 0.1


def die(message: str) -> None:
    raise ScriptError(f"Error: {message}", 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(sys.argv[0]),
        description=(
            "Run MicroBench at least 15 and at most 125 times on one isolated "
            "CPU. Discard the first 5 valid Scored time samples and stop when "
            "the two-sided 99% RMOE of the remaining samples is below 1%."
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

    if not command_exists("taskset"):
        die("taskset is not installed.")
    if not command_exists("sudo"):
        die("sudo is not installed.")

    effective_path = NEMU_CGROUP / "cpuset.cpus.effective"
    cgroup_procs = NEMU_CGROUP / "cgroup.procs"
    if not NEMU_CGROUP.is_dir():
        die(f"CPU isolation cgroup does not exist: {NEMU_CGROUP}")
    if not os.access(effective_path, os.R_OK):
        die(f"Cannot read {effective_path}")
    if (
        not os.access(cgroup_procs, os.W_OK)
        and subprocess.run(["sudo", "-v"], check=False).returncode != 0
    ):
        die("Cannot acquire permission to enter the isolated cgroup.")

    try:
        cpu_text = input("CPU to run on: ")
    except EOFError:
        die("Failed to read the CPU number.")

    if (
        not cpu_text.isascii()
        or not cpu_text.isdecimal()
        or (len(cpu_text) > 1 and cpu_text.startswith("0"))
    ):
        die("The CPU number must be a non-negative integer without leading zeros.")

    cpu_id = int(cpu_text)
    effective_cpus = read_text(effective_path)
    try:
        available_cpus = parse_cpu_list(effective_cpus, max_cpu_id(effective_cpus))
    except ValueError:
        die(f"Invalid isolated CPU list: {effective_cpus}")
    if cpu_id not in available_cpus:
        die(f"CPU{cpu_id} is not in the isolated cgroup (available: {effective_cpus}).")

    frequency_file = Path(
        f"/sys/devices/system/cpu/cpu{cpu_id}/cpufreq/scaling_cur_freq"
    )
    if not os.access(frequency_file, os.R_OK):
        die(f"Cannot read CPU{cpu_id} frequency from {frequency_file}.")

    microbench = os.environ.get("MICROBENCH")
    if not microbench:
        die("MICROBENCH is not set.")

    log_files = [config.output / f"log-{index}" for index in range(1, MAX_RUNS + 1)]
    existing_log = next((log_file for log_file in log_files if log_file.exists()), None)
    if existing_log is not None:
        die(f"output log already exists: {existing_log}")

    subprocess.run(
        ["sudo", "tee", str(cgroup_procs)],
        input=f"{os.getpid()}\n",
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        ["taskset", "-pc", str(cpu_id), str(os.getpid())],
        stdout=subprocess.DEVNULL,
        check=True,
    )

    print(f"CPU: {cpu_id}")
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
            f"[{index}/{MAX_RUNS}] Running make ARCH={config.arch} run on CPU{cpu_id}",
            flush=True,
        )

        with log_file.open("x", encoding="utf-8") as stream:
            try:
                process = subprocess.Popen(
                    make_run_command(microbench, config.arch),
                    cwd=SCRIPT_DIR,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            except OSError as exc:
                stream.write(f"{exc}\n")
                process = None

            frequency_sum_khz = 0
            frequency_sample_count = 0
            if process is not None:
                while process.poll() is None:
                    frequency_khz = sample_frequency(frequency_file)
                    if frequency_khz is not None:
                        frequency_sum_khz += frequency_khz
                        frequency_sample_count += 1
                    time.sleep(FREQ_SAMPLE_INTERVAL_SECONDS)
                status = normalize_returncode(process.returncode)
            else:
                status = 127

        if frequency_sample_count:
            message = (
                f"\nAverage CPU{cpu_id} frequency: "
                f"{average_frequency_mhz(frequency_sum_khz, frequency_sample_count)} "
                f"MHz ({frequency_sample_count} samples)"
            )
            print(message)
            with log_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{message}\n")
        else:
            message = f"\nAverage CPU{cpu_id} frequency: unavailable (no valid samples)"
            print(message, file=sys.stderr)
            with log_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{message}\n")

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
