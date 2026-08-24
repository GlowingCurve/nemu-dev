#!/usr/bin/env python3
"""Check whether the host is ready for runtime CPU isolation."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Isolation scripts are executable files in a subdirectory; expose shared helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import (  # noqa: E402
    NEMU_CGROUP,
    NEMU_IRQBALANCE_UNIT,
    NEMU_STATE,
    command_exists,
    main_guard,
    parse_kernel_cpu_list,
    read_text,
    try_read_text,
)
from _core_runtime import (  # noqa: E402
    ArgumentError,
    load_runtime_config,
    parse_cpu_argument,
)


class Reporter:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0

    @staticmethod
    def passed(message: str) -> None:
        print(f"[PASS] {message}", flush=True)

    def fail(self, message: str) -> None:
        print(f"[FAIL] {message}", file=sys.stderr, flush=True)
        self.failures += 1

    def warn(self, message: str) -> None:
        print(f"[WARN] {message}", file=sys.stderr, flush=True)
        self.warnings += 1

    def check_command(self, command: str) -> None:
        if command_exists(command):
            self.passed(f"找到命令：{command}")
        else:
            self.fail(f"缺少命令：{command}")


def command_stdout(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.rstrip("\n")


def print_selected_topology(cpus: set[int], reporter: Reporter) -> None:
    if not command_exists("lscpu"):
        return
    try:
        result = subprocess.run(
            ["lscpu", "-e=CPU,CORE,SOCKET,NODE,ONLINE"],
            stdout=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        reporter.fail("无法读取 lscpu 拓扑。")
        return

    if result.returncode != 0:
        reporter.fail("无法读取 lscpu 拓扑。")
        return
    for line_number, line in enumerate(result.stdout.splitlines()):
        fields = line.split()
        if line_number == 0 or (fields and fields[0].isdecimal() and int(fields[0]) in cpus):
            print(line)


def main() -> int:
    try:
        cpu_input = parse_cpu_argument(sys.argv)
        if cpu_input is None:
            return 0
        config = load_runtime_config(cpu_input, require_housekeeping=False)
    except ArgumentError as exc:
        return exc.status

    reporter = Reporter()
    isolated_set = config.isolated_set
    online_set = config.online_set

    print("NEMU 运行时 CPU 隔离预检查")
    print(f"目标 CPU：{config.isolated_cpus}")
    print(f"online CPU：{config.online_cpus}\n")

    if os.geteuid() == 0:
        reporter.fail("请在普通用户 shell 中运行本脚本，不要使用 sudo。")
    else:
        reporter.passed(f"当前用户不是 root（uid={os.geteuid()}）")

    for command in ("awk", "cat", "lscpu", "findmnt", "systemctl", "systemd-run"):
        reporter.check_command(command)

    irqbalance = Path("/usr/sbin/irqbalance")
    if os.access(irqbalance, os.X_OK):
        reporter.passed(f"找到可执行文件：{irqbalance}")
    else:
        reporter.fail(f"找不到可执行文件：{irqbalance}")

    for cpu in config.isolated_cpu_ids:
        if cpu in online_set:
            reporter.passed(f"CPU{cpu} online")
        else:
            reporter.fail(f"CPU{cpu} 不在 online CPU 列表 {config.online_cpus} 中。")

    if config.housekeeping_cpu_ids:
        reporter.passed(f"housekeeping CPU 将为 {config.housekeeping_cpus}")
    else:
        reporter.fail("不能隔离全部 online CPU；至少要保留一个 housekeeping CPU。")

    print("\nCPU 拓扑：")
    print_selected_topology(isolated_set, reporter)

    for cpu in config.isolated_cpu_ids:
        cpu_root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
        core_id = try_read_text(cpu_root / "topology/core_id")
        siblings = try_read_text(cpu_root / "topology/thread_siblings_list")

        if core_id.isascii() and core_id.isdecimal():
            reporter.passed(f"CPU{cpu} 的物理核心编号为 {core_id}")
        else:
            reporter.fail(f"无法读取 CPU{cpu} 的物理核心编号。")

        try:
            sibling_ids = parse_kernel_cpu_list(siblings, config.max_cpu_id)
        except ValueError:
            reporter.fail(
                f"CPU{cpu} 的 SMT siblings 无法读取或格式无效："
                f"{siblings or '<不可读>'}"
            )
            continue
        missing = [
            sibling
            for sibling in sibling_ids
            if sibling in online_set and sibling not in isolated_set
        ]
        if not missing:
            reporter.passed(f"CPU{cpu} 的 online SMT siblings 均已隔离（{siblings}）")
        else:
            reporter.fail(
                f"CPU{cpu} 的 online SMT sibling 未包含在目标列表中："
                f"{','.join(map(str, missing))}"
            )

    print("\ncgroup：")
    if command_exists("findmnt"):
        cgroup_type = command_stdout(
            ["findmnt", "-no", "FSTYPE", "/sys/fs/cgroup"])
        if cgroup_type == "cgroup2":
            reporter.passed("cgroup 文件系统为 cgroup2")
        else:
            reporter.fail(
                f"cgroup 文件系统应为 cgroup2，实际为 {cgroup_type or '<不可读>'}"
            )

    controllers = try_read_text("/sys/fs/cgroup/cgroup.controllers")
    if "cpuset" in controllers.split():
        reporter.passed("根 cgroup 提供 cpuset controller")
    else:
        reporter.fail(
            f"根 cgroup 的 controller 列表不包含 cpuset："
            f"{controllers or '<不可读>'}"
        )

    isolated_path = Path("/sys/fs/cgroup/cpuset.cpus.isolated")
    if os.access(isolated_path, os.R_OK):
        current_isolated = read_text(isolated_path)
        if not current_isolated:
            reporter.passed("当前没有 isolated cpuset partition")
        else:
            reporter.fail(
                f"当前已存在 isolated CPU（{current_isolated}），请先检查已有配置。"
            )
    else:
        reporter.fail("无法读取 /sys/fs/cgroup/cpuset.cpus.isolated。")

    if NEMU_CGROUP.exists():
        reporter.fail(f"发现残留 cgroup：{NEMU_CGROUP}")
    else:
        reporter.passed(f"未发现残留 cgroup：{NEMU_CGROUP}")
    if NEMU_STATE.exists():
        reporter.fail(f"发现残留状态目录：{NEMU_STATE}")
    else:
        reporter.passed(f"未发现残留状态目录：{NEMU_STATE}")

    print("\nCPUFreq：")
    for cpu in config.isolated_cpu_ids:
        policy = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
        driver = try_read_text(policy / "scaling_driver")
        governor = try_read_text(policy / "scaling_governor")
        min_freq = try_read_text(policy / "scaling_min_freq")
        max_freq = try_read_text(policy / "scaling_max_freq")
        hardware_max = try_read_text(policy / "cpuinfo_max_freq")
        affected = try_read_text(policy / "affected_cpus")
        epp = try_read_text(policy / "energy_performance_preference")

        print(
            f"CPU{cpu}: driver={driver or '?'} governor={governor or '?'} "
            f"epp={epp or '?'} min_kHz={min_freq or '?'} "
            f"max_kHz={max_freq or '?'} affected={affected or '?'}"
        )
        if driver == "amd-pstate-epp":
            reporter.passed(f"CPU{cpu} 使用 amd-pstate-epp")
        else:
            reporter.fail(
                f"CPU{cpu} 应使用 amd-pstate-epp，实际为 {driver or '<不可读>'}"
            )

        affected_ok = True
        affected_has_cpu = False
        try:
            affected_ids = parse_kernel_cpu_list(affected, config.max_cpu_id)
            for affected_cpu in affected_ids:
                if affected_cpu == cpu:
                    affected_has_cpu = True
                if affected_cpu not in isolated_set:
                    affected_ok = False
        except ValueError:
            affected_ok = False
        if not affected_has_cpu:
            affected_ok = False
        if affected_ok:
            reporter.passed(f"CPU{cpu} 的 cpufreq policy 只影响目标 CPU（{affected}）")
        else:
            reporter.fail(
                f"CPU{cpu} 的 cpufreq policy 会影响目标列表之外的 CPU："
                f"{affected or '<不可读>'}"
            )

        if hardware_max.isascii() and hardware_max.isdecimal() and int(hardware_max) >= 4_000_000:
            reporter.passed(
                f"CPU{cpu} 支持 4 GHz 上限（cpuinfo_max_freq={hardware_max} kHz）"
            )
        else:
            reporter.fail(
                f"CPU{cpu} 无法确认支持 4 GHz 上限"
                f"（cpuinfo_max_freq={hardware_max or '<不可读>'}）"
            )

        if not all((governor, min_freq, max_freq, epp)):
            reporter.fail(f"CPU{cpu} 缺少脚本需要的 CPUFreq/EPP 接口。")

    print("\nIRQ：")
    if command_exists("systemctl"):
        irqbalance_state = command_stdout(
            ["systemctl", "is-active", "irqbalance.service"]
        )
        if irqbalance_state == "active":
            reporter.passed("irqbalance.service 为 active")
        elif irqbalance_state == "inactive":
            reporter.warn("irqbalance.service 当前为 inactive；设置脚本会记录并保留这一原始状态。")
        else:
            reporter.fail(
                f"无法确认 irqbalance.service 状态，实际为 "
                f"{irqbalance_state or '<未知>'}"
            )

        transient_state = command_stdout(
            [
                "systemctl",
                "show",
                NEMU_IRQBALANCE_UNIT,
                "--property=LoadState",
                "--value",
            ]
        )
        if transient_state == "not-found":
            reporter.passed(f"未发现残留临时服务：{NEMU_IRQBALANCE_UNIT}")
        else:
            reporter.fail(
                f"临时服务 {NEMU_IRQBALANCE_UNIT} 仍存在"
                f"（LoadState={transient_state or '<未知>'}）。"
            )

    print()
    if reporter.failures:
        print(
            f"预检查失败：共发现 {reporter.failures} 个问题、"
            f"{reporter.warnings} 个警告。请修正或确认残留状态后再运行 root 设置脚本。",
            file=sys.stderr,
        )
        return 1

    print(
        f"预检查通过（{reporter.warnings} 个警告）。请使用相同参数运行："
        f"sudo ./scripts/setup_core_runtime_isolation.sh --cpus {config.isolated_cpus}"
    )
    return 0


if __name__ == "__main__":
    main_guard(main)
