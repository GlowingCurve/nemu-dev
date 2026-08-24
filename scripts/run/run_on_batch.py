#!/usr/bin/env python3
"""Run CPU-sized MicroBench batches until scored-time statistics stabilize."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

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
    normalize_returncode,
    parse_cpu_list,
    program_name,
    read_text,
    sample_frequency,
)
from _run_config import (  # noqa: E402
    add_run_config_arguments,
    make_run_command,
    resolve_run_config,
)

FREQ_SAMPLE_INTERVAL_SECONDS = 0.1


@dataclass
class Worker:
    run: int
    cpu: int
    log_file: Path
    stream: TextIO
    process: subprocess.Popen[bytes] | None
    frequency_sum_khz: int = 0
    frequency_sample_count: int = 0
    spawn_status: int = 0


def die(message: str) -> None:
    raise ScriptError(f"Error: {message}", 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=program_name(sys.argv[0]),
        description=(
            "Run MicroBench in parallel CPU-sized batches for at least 15 and "
            "at most 125 total runs. Discard the first 5 valid Scored time "
            "samples and stop when the two-sided 99% RMOE of the remaining "
            "samples is below 1%."
        ),
    )
    add_run_config_arguments(parser)
    return parser.parse_args()


def start_worker(
    run: int, cpu: int, log_file: Path, microbench: str, arch: str
) -> Worker:
    stream = log_file.open("x", encoding="utf-8")
    try:
        process = subprocess.Popen(
            ["taskset", "-c", str(cpu), *make_run_command(microbench, arch)],
            cwd=SCRIPT_DIR,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        return Worker(run, cpu, log_file, stream, process)
    except OSError as exc:
        stream.write(f"{exc}\n")
        stream.flush()
        return Worker(run, cpu, log_file, stream, None, spawn_status=127)


def monitor_workers(workers: list[Worker]) -> None:
    while any(
        worker.process is not None and worker.process.poll() is None
        for worker in workers
    ):
        for worker in workers:
            if worker.process is None or worker.process.poll() is not None:
                continue
            frequency_file = Path(
                f"/sys/devices/system/cpu/cpu{worker.cpu}/cpufreq/scaling_cur_freq"
            )
            frequency_khz = sample_frequency(frequency_file)
            if frequency_khz is not None:
                worker.frequency_sum_khz += frequency_khz
                worker.frequency_sample_count += 1
        time.sleep(FREQ_SAMPLE_INTERVAL_SECONDS)


def finish_worker(worker: Worker) -> int:
    if worker.process is None:
        status = worker.spawn_status
    else:
        status = normalize_returncode(worker.process.wait())

    if worker.frequency_sample_count:
        worker.stream.write(
            f"\nAverage CPU{worker.cpu} frequency: "
            f"{average_frequency_mhz(worker.frequency_sum_khz, worker.frequency_sample_count)} "
            f"MHz ({worker.frequency_sample_count} samples)\n"
        )
    else:
        worker.stream.write(
            f"\nAverage CPU{worker.cpu} frequency: unavailable (no valid samples)\n"
        )
    worker.stream.close()
    return status


def main() -> int:
    args = parse_args()
    config = resolve_run_config(args)

    # Check the statistics dependency before starting a potentially long run.
    student_t_critical_99(MIN_RUNS - WARMUP_RUNS)

    for command in ("make", "taskset", "sudo", "tee", "awk"):
        if not command_exists(command):
            die(f"{command} is not installed.")

    effective_path = NEMU_CGROUP / "cpuset.cpus.effective"
    partition_path = NEMU_CGROUP / "cpuset.cpus.partition"
    cgroup_procs = NEMU_CGROUP / "cgroup.procs"
    if not NEMU_CGROUP.is_dir():
        die(f"CPU isolation cgroup does not exist: {NEMU_CGROUP}")
    if not os.access(effective_path, os.R_OK):
        die(f"Cannot read {effective_path}")
    if not os.access(partition_path, os.R_OK):
        die(f"Cannot read {partition_path}")
    if read_text(partition_path) != "isolated":
        die(f"The target cgroup is not an isolated cpuset partition: {NEMU_CGROUP}")
    if (
        not os.access(cgroup_procs, os.W_OK)
        and subprocess.run(["sudo", "-v"], check=False).returncode != 0
    ):
        die("Cannot acquire permission to enter the isolated cgroup.")

    effective_cpus = read_text(effective_path)
    try:
        isolated_cpus = parse_cpu_list(effective_cpus, 31)
    except ValueError:
        die(f"Invalid isolated CPU list or CPU ID outside 0-31: {effective_cpus}")

    isolated_cpu_set = set(isolated_cpus)
    lower_cpus = [cpu for cpu in isolated_cpus if cpu < 16]
    upper_cpus = [cpu for cpu in isolated_cpus if cpu >= 16]
    if not lower_cpus:
        die("The isolated CPU list contains no CPU numbered below 16.")
    if len(lower_cpus) != len(upper_cpus):
        die(
            "The two CPU clusters have different sizes: "
            f"lower={len(lower_cpus)}, upper={len(upper_cpus)}."
        )

    for cpu in lower_cpus:
        paired_cpu = cpu + 16
        if paired_cpu not in isolated_cpu_set:
            die(f"CPU{cpu} has no isolated CPU{paired_cpu} counterpart.")
        frequency_file = Path(
            f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq"
        )
        if not os.access(frequency_file, os.R_OK):
            die(f"Cannot read CPU{cpu} frequency from {frequency_file}.")
    for cpu in upper_cpus:
        paired_cpu = cpu - 16
        if paired_cpu not in isolated_cpu_set:
            die(f"CPU{cpu} has no isolated CPU{paired_cpu} counterpart.")

    batch_size = len(lower_cpus)
    max_batch_count = (MAX_RUNS + batch_size - 1) // batch_size

    microbench = os.environ.get("MICROBENCH")
    if not microbench:
        die("MICROBENCH is not set.")

    log_files = [config.output / f"log-{run}" for run in range(1, MAX_RUNS + 1)]
    existing_log = next(
        (log_file for log_file in log_files if log_file.exists()),
        None,
    )
    if existing_log is not None:
        die(f"output log already exists: {existing_log}")

    subprocess.run(
        ["sudo", "tee", str(cgroup_procs)],
        input=f"{os.getpid()}\n",
        text=True,
        stdout=subprocess.DEVNULL,
        check=True,
    )

    print(f"Isolated CPUs: {effective_cpus}")
    print(f"Worker CPUs: {' '.join(map(str, lower_cpus))}")
    print(f"ARCH: {config.arch}")
    print(f"BATCH: {batch_size}")
    print(
        f"Runs: minimum {MIN_RUNS}, maximum {MAX_RUNS} "
        f"(at most {max_batch_count} batches)"
    )
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
    for batch in range(1, max_batch_count + 1):
        first_run = (batch - 1) * batch_size + 1
        last_run = min(batch * batch_size, MAX_RUNS)
        batch_runs = list(range(first_run, last_run + 1))
        batch_cpus = lower_cpus[: len(batch_runs)]
        print(
            f"[batch {batch}/{max_batch_count}] Starting {len(batch_runs)} run(s).",
            flush=True,
        )

        workers: list[Worker] = []
        for run, cpu in zip(batch_runs, batch_cpus, strict=True):
            log_file = log_files[run - 1]
            print(
                f"[batch {batch}/{max_batch_count}] Starting run {run} on "
                f"CPU{cpu}: {log_file}",
                flush=True,
            )
            workers.append(start_worker(run, cpu, log_file, microbench, config.arch))

        monitor_workers(workers)
        batch_failed = 0
        for worker in workers:
            status = finish_worker(worker)
            if status != 0:
                print(
                    f"[batch {batch}/{max_batch_count}] Run {worker.run} on "
                    f"CPU{worker.cpu} failed with status {status}: "
                    f"{worker.log_file}",
                    file=sys.stderr,
                    flush=True,
                )
                batch_failed += 1
            else:
                try:
                    scored_time_ms = extract_scored_time_ms(worker.log_file)
                except ValueError as exc:
                    print(
                        f"[batch {batch}/{max_batch_count}] Run {worker.run} "
                        f"on CPU{worker.cpu} produced an invalid benchmark log: "
                        f"{exc}: {worker.log_file}",
                        file=sys.stderr,
                        flush=True,
                    )
                    batch_failed += 1
                else:
                    scored_times_ms.append(scored_time_ms)
                    print(
                        f"[batch {batch}/{max_batch_count}] Run {worker.run} "
                        f"on CPU{worker.cpu} finished: {worker.log_file} "
                        f"(Scored time: {scored_time_ms:.4f} ms)",
                        flush=True,
                    )

        failed += batch_failed
        attempts = last_run
        print(
            f"[batch {batch}/{max_batch_count}] Complete ({batch_failed} failure(s)).",
            flush=True,
        )

        if len(scored_times_ms) < MIN_RUNS:
            if attempts >= MIN_RUNS:
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
