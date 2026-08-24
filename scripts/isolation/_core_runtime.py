"""Shared argument and host-state handling for CPU runtime isolation."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, TextIO

from _common import (
    ScriptError,
    cpus_to_mask,
    format_cpu_list,
    max_cpu_id,
    parse_cpu_list,
    program_name,
    read_text,
)


POSSIBLE_CPUS_PATH = Path("/sys/devices/system/cpu/possible")
ONLINE_CPUS_PATH = Path("/sys/devices/system/cpu/online")


class ArgumentError(ScriptError):
    pass


def usage(program: str, stream: TextIO = sys.stdout) -> None:
    print(f"用法：{program} CPU列表", file=stream)
    print(f"      {program} [-c|--cpus] CPU列表", file=stream)
    print(file=stream)
    print(
        "CPU列表使用 Linux cpulist 格式，例如 7,23 或 4-5,20-21。",
        file=stream,
    )


def argument_error(program: str, message: str) -> NoReturn:
    print(f"参数错误：{message}\n", file=sys.stderr)
    usage(program, sys.stderr)
    raise ArgumentError("", 2)


def parse_cpu_argument(argv: list[str]) -> str | None:
    program = program_name(argv[0])
    args = argv[1:]
    if len(args) == 1:
        value = args[0]
        if value in {"-h", "--help"}:
            usage(program)
            return None
        if value.startswith("--cpus="):
            value = value.partition("=")[2]
            if not value:
                argument_error(program, "--cpus 的值不能为空。")
        elif value.startswith("-"):
            argument_error(program, f"未知选项：{value}")
        return value
    if len(args) == 2:
        if args[0] not in {"-c", "--cpus"}:
            argument_error(program, f"未知选项或多余参数：{args[0]}")
        return args[1]
    if not args:
        argument_error(program, "必须指定要隔离的 CPU 列表。")
    argument_error(program, "参数过多。")


@dataclass(frozen=True)
class RuntimeConfig:
    input_cpus: str
    possible_cpus: str
    online_cpus: str
    max_cpu_id: int
    isolated_cpu_ids: list[int]
    possible_cpu_ids: list[int]
    online_cpu_ids: list[int]
    housekeeping_cpu_ids: list[int]

    @property
    def isolated_cpus(self) -> str:
        return format_cpu_list(self.isolated_cpu_ids)

    @property
    def housekeeping_cpus(self) -> str:
        return format_cpu_list(self.housekeeping_cpu_ids)

    @property
    def isolated_mask(self) -> str:
        return cpus_to_mask(self.isolated_cpu_ids, self.max_cpu_id)

    @property
    def housekeeping_mask(self) -> str:
        return cpus_to_mask(self.housekeeping_cpu_ids, self.max_cpu_id)

    @property
    def isolated_set(self) -> set[int]:
        return set(self.isolated_cpu_ids)

    @property
    def online_set(self) -> set[int]:
        return set(self.online_cpu_ids)


def load_runtime_config(cpu_input: str, *, require_housekeeping: bool) -> RuntimeConfig:
    program = program_name(sys.argv[0])
    if not os.access(POSSIBLE_CPUS_PATH, os.R_OK):
        argument_error(program, "无法读取系统 possible CPU 列表。")
    possible_cpus = read_text(POSSIBLE_CPUS_PATH)
    try:
        maximum = max_cpu_id(possible_cpus)
    except ValueError:
        argument_error(program, f"系统 possible CPU 列表格式无效：{possible_cpus}")

    try:
        isolated_ids = parse_cpu_list(cpu_input, maximum)
    except ValueError:
        argument_error(
            program,
            f"CPU 列表格式无效或超出 possible 范围 0-{maximum}：{cpu_input}",
        )
    try:
        possible_ids = parse_cpu_list(possible_cpus, maximum)
    except ValueError:
        argument_error(program, f"系统 possible CPU 列表格式无效：{possible_cpus}")

    if not os.access(ONLINE_CPUS_PATH, os.R_OK):
        argument_error(program, "无法读取系统 online CPU 列表。")
    online_cpus = read_text(ONLINE_CPUS_PATH)
    try:
        online_ids = parse_cpu_list(online_cpus, maximum)
    except ValueError:
        argument_error(program, f"系统 online CPU 列表格式无效：{online_cpus}")

    isolated_set = set(isolated_ids)
    housekeeping_ids = [cpu for cpu in online_ids if cpu not in isolated_set]
    if require_housekeeping and not housekeeping_ids:
        argument_error(program, "不能隔离全部 online CPU；至少要保留一个 housekeeping CPU。")

    return RuntimeConfig(
        input_cpus=cpu_input,
        possible_cpus=possible_cpus,
        online_cpus=online_cpus,
        max_cpu_id=maximum,
        isolated_cpu_ids=isolated_ids,
        possible_cpu_ids=possible_ids,
        online_cpu_ids=online_ids,
        housekeeping_cpu_ids=housekeeping_ids,
    )
