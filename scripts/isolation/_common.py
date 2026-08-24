"""Shared helpers for the microbench maintenance scripts."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn, Sequence


NEMU_CGROUP = Path("/sys/fs/cgroup/nemu-core7-runtime")
NEMU_STATE = Path("/run/nemu-core7-runtime-state")
NEMU_IRQBALANCE_UNIT = "irqbalance-nemu-core7.service"

_CPU_LIST_RE = re.compile(r"[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*")
_CPU_MASK_RE = re.compile(r"[0-9a-fA-F]{1,8}(?:,[0-9a-fA-F]{1,8})*")
_PROGRAM_NAME_OVERRIDE = os.environ.pop("NEMU_SCRIPT_NAME", None)


class ScriptError(Exception):
    """An expected script failure with a user-facing message and exit status."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


def error(message: str, *, status: int = 2, prefix: str = "Error") -> NoReturn:
    raise ScriptError(f"{prefix}: {message}", status)


def print_error(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def program_name(argv0: str) -> str:
    """Return the compatibility entrypoint name when launched by a wrapper."""
    return _PROGRAM_NAME_OVERRIDE or Path(argv0).name


def timestamp_ns() -> str:
    now = time.time_ns()
    seconds, nanoseconds = divmod(now, 1_000_000_000)
    return time.strftime("%Y%m%d_%H%M%S", time.localtime(seconds)) + (
        f"_{nanoseconds:09d}"
    )


def read_text(path: Path | str) -> str:
    """Read a kernel-style text file, matching shell command substitution."""
    return Path(path).read_text(encoding="utf-8").rstrip("\n")


def try_read_text(path: Path | str) -> str:
    try:
        return read_text(path)
    except OSError:
        return ""


def write_value(path: Path | str, value: object) -> None:
    Path(path).write_text(f"{value}\n", encoding="utf-8")


def require_command(command: str, message: str | None = None) -> str:
    path = shutil.which(command)
    if path is None:
        raise ScriptError(message or f"缺少命令：{command}")
    return path


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run(
    args: Sequence[str],
    *,
    check: bool = False,
    capture_output: bool = False,
    quiet: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    stdout = subprocess.DEVNULL if quiet else (subprocess.PIPE if capture_output else None)
    stderr = subprocess.PIPE if capture_output else None
    return subprocess.run(
        list(args),
        check=check,
        input=input_text,
        text=True,
        stdout=stdout,
        stderr=stderr,
    )


def parse_cpu_list(cpu_list: str, max_cpu: int) -> list[int]:
    """Parse Linux cpulist syntax, returning a sorted, de-duplicated list."""
    compact = "".join(cpu_list.split())
    if not compact or _CPU_LIST_RE.fullmatch(compact) is None:
        raise ValueError(f"invalid CPU list: {cpu_list}")

    cpus: set[int] = set()
    for item in compact.split(","):
        bounds = item.split("-", 1)
        if any(len(bound) > 1 and bound.startswith("0") for bound in bounds):
            raise ValueError(f"invalid leading zero in CPU list: {cpu_list}")
        start = int(bounds[0])
        end = int(bounds[-1])
        if start > end or end > max_cpu:
            raise ValueError(f"CPU outside range 0-{max_cpu}: {item}")
        cpus.update(range(start, end + 1))

    if not cpus:
        raise ValueError("CPU list is empty")
    return sorted(cpus)


def parse_kernel_cpu_list(cpu_list: str, max_cpu: int) -> list[int]:
    fields = cpu_list.replace(",", " ").split()
    if not fields:
        raise ValueError("CPU list is empty")
    return parse_cpu_list(",".join(fields), max_cpu)


def max_cpu_id(cpu_list: str) -> int:
    compact = "".join(cpu_list.split())
    if not compact or _CPU_LIST_RE.fullmatch(compact) is None:
        raise ValueError(f"invalid CPU list: {cpu_list}")

    maximum = -1
    for item in compact.split(","):
        bounds = item.split("-", 1)
        if any(len(bound) > 1 and bound.startswith("0") for bound in bounds):
            raise ValueError(f"invalid leading zero in CPU list: {cpu_list}")
        maximum = max(maximum, int(bounds[-1]))
    return maximum


def format_cpu_list(cpus: Sequence[int]) -> str:
    ordered = sorted(set(cpus))
    if not ordered:
        raise ValueError("CPU list is empty")

    ranges: list[str] = []
    start = previous = ordered[0]
    for cpu in ordered[1:]:
        if cpu == previous + 1:
            previous = cpu
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = cpu
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def cpus_to_mask(cpus: Sequence[int], max_cpu: int) -> str:
    groups = [0] * (max_cpu // 32 + 1)
    for cpu in cpus:
        groups[cpu // 32] |= 1 << (cpu % 32)
    return ",".join(f"{word:08x}" for word in reversed(groups))


def parse_cpu_mask(mask: str) -> list[int]:
    compact = "".join(mask.split())
    if _CPU_MASK_RE.fullmatch(compact) is None:
        raise ValueError(f"invalid CPU mask: {mask}")

    cpus: list[int] = []
    groups = compact.split(",")
    for group_from_right, word in enumerate(reversed(groups)):
        value = int(word, 16)
        for bit in range(32):
            if value & (1 << bit):
                cpus.append(group_from_right * 32 + bit)
    return cpus


def normalize_returncode(returncode: int) -> int:
    """Translate subprocess signal return codes to the shell's 128+signal form."""
    return 128 - returncode if returncode < 0 else returncode


def average_frequency_mhz(total_khz: int, sample_count: int) -> str:
    return f"{total_khz / sample_count / 1000:.2f}"


def sample_frequency(path: Path) -> int | None:
    try:
        value = read_text(path)
    except OSError:
        return None
    if not value.isascii() or not value.isdecimal() or value.startswith("0"):
        return None
    return int(value)


def main_guard(function: object) -> None:
    """Run a script main function with consistent expected-error handling."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)
    try:
        status = function()  # type: ignore[operator]
    except ScriptError as exc:
        print_error(str(exc))
        status = exc.status
    except subprocess.CalledProcessError as exc:
        status = normalize_returncode(exc.returncode)
    except OSError as exc:
        print_error(f"Error: {exc}")
        status = 1
    except KeyboardInterrupt:
        print_error("\nInterrupted.")
        status = 130
    raise SystemExit(status or 0)
