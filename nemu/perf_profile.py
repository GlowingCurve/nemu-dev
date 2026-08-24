#!/usr/bin/env python3
"""Build NEMU for profiling, record perf data, then restore a normal build."""

from pathlib import Path
import shlex
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent

PROFILE_COMMANDS = (
    ("make", "clean"),
    ("make", "PROFILE=1"),
    (
        "perf",
        "record",
        "-o",
        "perf.data",
        "-F",
        "5000",
        "--call-graph",
        "fp",
        "--",
        "./build/riscv32-nemu-interpreter",
        "-b",
        "../microbench/build/microbench-riscv32-nemu.bin",
    ),
)

RESTORE_COMMANDS = (
    ("make", "clean"),
    ("make",),
)


def run_commands(commands):
    for command in commands:
        print(f"+ {shlex.join(command)}", flush=True)
        subprocess.run(command, cwd=REPO_ROOT, check=True)


def failure_exit_code(error):
    if isinstance(error, subprocess.CalledProcessError):
        return error.returncode if error.returncode > 0 else 1
    if isinstance(error, KeyboardInterrupt):
        return 130
    return 127


def describe_failure(stage, error):
    if isinstance(error, subprocess.CalledProcessError):
        command = shlex.join(str(part) for part in error.cmd)
        print(
            f"{stage} failed with exit code {error.returncode}: {command}",
            file=sys.stderr,
        )
    elif isinstance(error, FileNotFoundError):
        print(f"{stage} failed: command not found: {error.filename}",
              file=sys.stderr)
    else:
        print(f"{stage} interrupted", file=sys.stderr)


def main():
    profile_error = None
    try:
        run_commands(PROFILE_COMMANDS)
    except (subprocess.CalledProcessError, FileNotFoundError, KeyboardInterrupt) as error:
        profile_error = error
        describe_failure("Profiling", error)

    restore_error = None
    try:
        run_commands(RESTORE_COMMANDS)
    except (subprocess.CalledProcessError, FileNotFoundError, KeyboardInterrupt) as error:
        restore_error = error
        describe_failure("Normal-build restoration", error)

    if profile_error is not None:
        return failure_exit_code(profile_error)
    if restore_error is not None:
        return failure_exit_code(restore_error)
    return 0


if __name__ == "__main__":
    sys.exit(main())
