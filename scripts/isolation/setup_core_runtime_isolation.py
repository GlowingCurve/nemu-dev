#!/usr/bin/env python3
"""Configure a reboot-ephemeral isolated cpuset for NEMU benchmarks."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
# Isolation scripts are executable files in a subdirectory; expose shared helpers.
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import (  # noqa: E402
    NEMU_CGROUP,
    NEMU_IRQBALANCE_UNIT,
    NEMU_STATE,
    ScriptError,
    command_exists,
    parse_cpu_list,
    parse_cpu_mask,
    parse_kernel_cpu_list,
    read_text,
    write_value,
)
from _core_runtime import (  # noqa: E402
    ArgumentError,
    RuntimeConfig,
    load_runtime_config,
    parse_cpu_argument,
)


class SetupError(ScriptError):
    pass


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


class IsolationSetup:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.irq_setup_started = False

    def die(self, message: str) -> None:
        raise SetupError(message, 1)

    def read_file(self, path: Path | str) -> str:
        path = Path(path)
        if not os.access(path, os.R_OK):
            self.die(f"无法读取 {path}")
        try:
            return read_text(path)
        except OSError:
            self.die(f"无法读取 {path}")

    def require_value(self, path: Path | str, expected: str, description: str) -> None:
        actual = self.read_file(path)
        if actual != expected:
            self.die(f"{description} 应为 {expected}，实际为 {actual or '<空>'}")

    def require_cpumask_for_cpus(
        self, path: Path | str, expected_cpus: list[int], description: str
    ) -> None:
        actual = self.read_file(path)
        try:
            actual_set = set(parse_cpu_mask(actual))
        except ValueError:
            self.die(f"{description} 格式无效：{actual}")
        expected_set = set(expected_cpus)
        for cpu in range(self.config.max_cpu_id + 1):
            if (cpu in actual_set) != (cpu in expected_set):
                self.die(f"{description} 与目标 CPU 集合不符：{actual}")

    def require_workqueue_masks(self) -> None:
        requested_path = Path("/sys/devices/virtual/workqueue/cpumask_requested")
        isolated_path = Path("/sys/devices/virtual/workqueue/cpumask_isolated")
        effective_path = Path("/sys/devices/virtual/workqueue/cpumask")
        requested = self.read_file(requested_path)
        isolated = self.read_file(isolated_path)
        effective = self.read_file(effective_path)
        try:
            requested_set = set(parse_cpu_mask(requested))
        except ValueError:
            self.die(f"workqueue requested mask 格式无效：{requested}")
        try:
            parse_cpu_mask(isolated)
        except ValueError:
            self.die(f"workqueue isolated mask 格式无效：{isolated}")
        self.require_cpumask_for_cpus(
            isolated_path,
            self.config.isolated_cpu_ids,
            "workqueue isolated mask",
        )
        try:
            effective_set = set(parse_cpu_mask(effective))
        except ValueError:
            self.die(f"workqueue effective mask 格式无效：{effective}")

        isolated_set = self.config.isolated_set
        for cpu in range(self.config.max_cpu_id + 1):
            expected = cpu in requested_set and cpu not in isolated_set
            actual = cpu in effective_set
            if actual != expected:
                self.die(
                    f"workqueue effective mask 在 CPU{cpu} 上不符合 "
                    f"requested - isolated：requested={requested} "
                    f"isolated={isolated} effective={effective}"
                )

    def restore_irqbalance_after_error(self) -> None:
        if not self.irq_setup_started:
            return
        subprocess.run(
            ["systemctl", "stop", NEMU_IRQBALANCE_UNIT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        prior_state = NEMU_STATE / "irqbalance.was_active"
        if os.access(prior_state, os.R_OK) and read_text(prior_state) == "active":
            subprocess.run(
                ["systemctl", "start", "irqbalance.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def report_failure(self, message: str, status: int = 1) -> int:
        self.restore_irqbalance_after_error()
        print(f"错误：{message}", file=sys.stderr)
        if NEMU_STATE.is_dir():
            print(
                f"运行时状态备份保留在 {NEMU_STATE}；"
                "继续操作前请按文档第 10.2 节检查并回滚。",
                file=sys.stderr,
            )
        return status

    def check_prerequisites(self) -> None:
        config = self.config
        if os.geteuid() != 0:
            self.die("本脚本必须以 root 身份运行；请使用 sudo。")

        for command in (
            "cat",
            "findmnt",
            "grep",
            "install",
            "mkdir",
            "systemctl",
            "systemd-run",
            "sleep",
        ):
            if not command_exists(command):
                self.die(f"缺少命令：{command}")

        if not os.access("/usr/sbin/irqbalance", os.X_OK):
            self.die("找不到可执行文件：/usr/sbin/irqbalance")

        if command_stdout(["findmnt", "-no", "FSTYPE", "/sys/fs/cgroup"]) != "cgroup2":
            self.die("/sys/fs/cgroup 不是 cgroup2。")

        controllers = self.read_file("/sys/fs/cgroup/cgroup.controllers")
        if "cpuset" not in controllers.split():
            self.die("根 cgroup 不提供 cpuset controller。")
        if self.read_file("/sys/fs/cgroup/cpuset.cpus.isolated"):
            self.die("系统已经存在 isolated CPU，请先检查现有配置。")
        if NEMU_CGROUP.exists():
            self.die(f"发现残留 cgroup：{NEMU_CGROUP}")
        if NEMU_STATE.exists():
            self.die(f"发现残留状态目录：{NEMU_STATE}")

        transient_state = command_stdout(
            [
                "systemctl",
                "show",
                NEMU_IRQBALANCE_UNIT,
                "--property=LoadState",
                "--value",
            ]
        )
        if transient_state != "not-found":
            self.die(
                f"临时服务 {NEMU_IRQBALANCE_UNIT} 已存在"
                f"（LoadState={transient_state or '<未知>'}）。"
            )

        print(
            f"目标 isolated CPU：{config.isolated_cpus}"
            f"（mask={config.isolated_mask}）"
        )
        print(
            f"自动推导 housekeeping CPU：{config.housekeeping_cpus}"
            f"（mask={config.housekeeping_mask}）"
        )

        for cpu in config.isolated_cpu_ids:
            cpu_root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
            policy = cpu_root / "cpufreq"
            if cpu not in config.online_set:
                self.die(f"CPU{cpu} 不在 online CPU 列表 {config.online_cpus} 中。")

            core_id = self.read_file(cpu_root / "topology/core_id")
            if not core_id.isascii() or not core_id.isdecimal():
                self.die(f"CPU{cpu} 的物理核心编号无效：{core_id}")

            siblings = self.read_file(cpu_root / "topology/thread_siblings_list")
            try:
                sibling_ids = parse_cpu_list(siblings, config.max_cpu_id)
            except ValueError:
                self.die(f"CPU{cpu} 的 SMT siblings 格式无效：{siblings}")
            for sibling in sibling_ids:
                if sibling in config.online_set and sibling not in config.isolated_set:
                    self.die(
                        f"CPU{cpu} 的 online SMT sibling CPU{sibling} "
                        f"未包含在目标列表 {config.isolated_cpus} 中。"
                    )

            self.require_value(policy / "scaling_driver", "amd-pstate-epp", f"CPU{cpu} scaling driver")

            affected = self.read_file(policy / "affected_cpus")
            try:
                affected_ids = parse_kernel_cpu_list(affected, config.max_cpu_id)
            except ValueError:
                self.die(f"CPU{cpu} affected_cpus 格式无效：{affected}")
            affected_has_cpu = False
            for affected_cpu in affected_ids:
                if affected_cpu == cpu:
                    affected_has_cpu = True
                if affected_cpu not in config.isolated_set:
                    self.die(
                        f"CPU{cpu} 的 cpufreq policy 会影响目标列表之外的 "
                        f"CPU{affected_cpu}。"
                    )
            if not affected_has_cpu:
                self.die(
                    f"CPU{cpu} 不在自身 cpufreq policy 的 affected_cpus 中：{affected}"
                )

            hardware_max = self.read_file(policy / "cpuinfo_max_freq")
            if (
                not hardware_max.isascii()
                or not hardware_max.isdecimal()
                or int(hardware_max) < 4_000_000
            ):
                self.die(
                    f"CPU{cpu} 的 cpuinfo_max_freq 不支持 4 GHz：{hardware_max}"
                )

            for field in (
                "scaling_min_freq",
                "scaling_max_freq",
                "scaling_governor",
                "energy_performance_preference",
            ):
                path = policy / field
                if not os.access(path, os.R_OK | os.W_OK):
                    self.die(f"CPU{cpu} 的 {field} 不可读写。")

        for path in (
            Path("/sys/fs/cgroup/cgroup.subtree_control"),
            Path("/proc/sys/kernel/watchdog_cpumask"),
            Path("/proc/irq/default_smp_affinity"),
        ):
            if not os.access(path, os.R_OK | os.W_OK):
                self.die(f"接口不可读写：{path}")

    def backup_state(self) -> None:
        config = self.config
        print("所有 root 前置条件已通过，开始备份运行时状态。")

        (NEMU_STATE / "irq").mkdir(parents=True, mode=0o700)
        os.chmod(NEMU_STATE, 0o700)
        os.chmod(NEMU_STATE / "irq", 0o700)

        write_value(NEMU_STATE / "isolated_cpus", config.isolated_cpus)
        write_value(
            NEMU_STATE / "isolated_cpu_ids",
            " ".join(map(str, config.isolated_cpu_ids)),
        )
        write_value(NEMU_STATE / "housekeeping_cpus", config.housekeeping_cpus)
        write_value(
            NEMU_STATE / "root.subtree_control",
            self.read_file("/sys/fs/cgroup/cgroup.subtree_control"),
        )
        write_value(
            NEMU_STATE / "watchdog_cpumask",
            self.read_file("/proc/sys/kernel/watchdog_cpumask"),
        )
        write_value(
            NEMU_STATE / "default_smp_affinity",
            self.read_file("/proc/irq/default_smp_affinity"),
        )

        irqbalance_active = (
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "irqbalance.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )
        write_value(
            NEMU_STATE / "irqbalance.was_active",
            "active" if irqbalance_active else "inactive",
        )

        for cpu in config.isolated_cpu_ids:
            policy = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
            for field in (
                "scaling_min_freq",
                "scaling_max_freq",
                "scaling_governor",
                "energy_performance_preference",
            ):
                write_value(
                    NEMU_STATE / f"cpu{cpu}.{field}",
                    self.read_file(policy / field),
                )

        irq_paths = sorted(Path("/proc/irq").glob("[0-9]*/smp_affinity_list"))
        if not irq_paths:
            self.die("没有找到可备份的 IRQ affinity。")
        irq_backup_count = 0
        for path in irq_paths:
            irq_number = path.parent.name
            try:
                affinity = read_text(path)
            except OSError:
                print(
                    f"警告：IRQ {irq_number} 在备份过程中消失，已跳过。",
                    file=sys.stderr,
                )
                continue
            write_value(NEMU_STATE / "irq" / irq_number, affinity)
            irq_backup_count += 1

        original_state = self.read_file(NEMU_STATE / "irqbalance.was_active")
        print(
            f"备份完成：{NEMU_STATE}（IRQ {irq_backup_count} 项，"
            f"irqbalance 原状态为 {original_state}）。"
        )

    def create_cpuset(self) -> None:
        config = self.config
        write_value("/sys/fs/cgroup/cgroup.subtree_control", "+cpuset")
        if "cpuset" not in self.read_file("/sys/fs/cgroup/cgroup.subtree_control").split():
            self.die("无法在根 cgroup 启用 cpuset controller。")

        NEMU_CGROUP.mkdir()
        memory_nodes = self.read_file("/sys/fs/cgroup/cpuset.mems.effective")
        if not memory_nodes:
            self.die("根 cgroup 的 cpuset.mems.effective 为空。")
        write_value(NEMU_CGROUP / "cpuset.mems", memory_nodes)
        write_value(NEMU_CGROUP / "cpuset.cpus", config.isolated_cpus)
        write_value(NEMU_CGROUP / "cpuset.cpus.partition", "isolated")

        self.require_value(
            NEMU_CGROUP / "cpuset.cpus", config.isolated_cpus, "cgroup requested CPU"
        )
        self.require_value(
            NEMU_CGROUP / "cpuset.cpus.effective",
            config.isolated_cpus,
            "cgroup effective CPU",
        )
        self.require_value(
            NEMU_CGROUP / "cpuset.cpus.exclusive.effective",
            config.isolated_cpus,
            "cgroup exclusive CPU",
        )
        self.require_value(
            NEMU_CGROUP / "cpuset.cpus.partition", "isolated", "cgroup partition 状态"
        )
        self.require_value(
            "/sys/fs/cgroup/cpuset.cpus.isolated",
            config.isolated_cpus,
            "系统 isolated CPU",
        )
        self.require_workqueue_masks()
        if self.read_file(NEMU_CGROUP / "cgroup.procs"):
            self.die("新建的目标 cgroup 中意外出现了进程。")
        print("isolated cpuset partition 已创建。")

    def configure_frequency_and_watchdog(self) -> None:
        config = self.config
        for cpu in config.isolated_cpu_ids:
            policy = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
            write_value(policy / "scaling_governor", "performance")
            write_value(policy / "energy_performance_preference", "performance")
            write_value(policy / "scaling_max_freq", "4000000")

        # scaling_max_freq updates the Frequency QoS request first; the cpufreq
        # policy itself is refreshed asynchronously by a kernel workqueue.
        time.sleep(1)

        for cpu in config.isolated_cpu_ids:
            policy = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
            self.require_value(
                policy / "scaling_governor", "performance", f"CPU{cpu} governor"
            )
            self.require_value(
                policy / "energy_performance_preference", "performance", f"CPU{cpu} EPP"
            )
            self.require_value(
                policy / "scaling_max_freq", "4000000", f"CPU{cpu} 最高频率（kHz）"
            )

        write_value("/proc/sys/kernel/watchdog_cpumask", config.housekeeping_cpus)
        self.require_value(
            "/proc/sys/kernel/watchdog_cpumask",
            config.housekeeping_cpus,
            "watchdog CPU 列表",
        )
        print("CPUFreq 和 watchdog 已配置。")

    def configure_irq(self) -> None:
        config = self.config
        self.irq_setup_started = True
        subprocess.run(
            ["systemctl", "stop", "irqbalance.service"], check=True
        )
        write_value("/proc/irq/default_smp_affinity", config.housekeeping_mask)
        self.require_cpumask_for_cpus(
            "/proc/irq/default_smp_affinity",
            config.housekeeping_cpu_ids,
            "默认 IRQ affinity",
        )

        result = subprocess.run(
            [
                "systemd-run",
                f"--unit={NEMU_IRQBALANCE_UNIT.removesuffix('.service')}",
                "--collect",
                f"--setenv=IRQBALANCE_BANNED_CPULIST={config.isolated_cpus}",
                "/usr/sbin/irqbalance",
                "--foreground",
            ],
            check=False,
        )
        if result.returncode != 0:
            self.die("临时 irqbalance 服务启动失败；已尝试恢复原 irqbalance 服务。")

        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", NEMU_IRQBALANCE_UNIT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if active.returncode != 0:
            self.die(
                f"临时服务 {NEMU_IRQBALANCE_UNIT} 未成功进入 active 状态；"
                "已尝试恢复原 irqbalance 服务。"
            )

        substate = command_stdout(
            [
                "systemctl",
                "show",
                NEMU_IRQBALANCE_UNIT,
                "--property=SubState",
                "--value",
            ]
        )
        if substate != "running":
            self.die(
                f"临时 irqbalance 服务的 SubState 应为 running，"
                f"实际为 {substate or '<未知>'}"
            )

        environment = command_stdout(
            [
                "systemctl",
                "show",
                NEMU_IRQBALANCE_UNIT,
                "--property=Environment",
                "--value",
            ]
        )
        expected = f"IRQBALANCE_BANNED_CPULIST={config.isolated_cpus}"
        if expected not in environment.split():
            self.die(f"临时 irqbalance 服务缺少正确的 banned CPU 配置：{environment}")

        print("临时 irqbalance 已启动，等待首次重新平衡（12 秒）。")
        time.sleep(12)

        remaining_irq_count = 0
        effective_paths = sorted(
            Path("/proc/irq").glob("[0-9]*/effective_affinity_list")
        )
        for path in effective_paths:
            try:
                effective = read_text(path)
            except OSError:
                print(f"警告：{path} 在 IRQ 检查过程中消失，已跳过。", file=sys.stderr)
                continue
            try:
                effective_cpus = set(parse_cpu_list(effective, config.max_cpu_id))
            except ValueError:
                effective_cpus = set()
            if not effective_cpus.intersection(config.isolated_set):
                continue

            irq_number = path.parent.name
            requested_path = path.parent / "smp_affinity_list"
            try:
                requested = read_text(requested_path)
            except OSError:
                print(
                    f"警告：IRQ {irq_number} 在检查过程中消失，已跳过。",
                    file=sys.stderr,
                )
                continue
            print(
                f"警告：IRQ {irq_number} 仍使用隔离 CPU："
                f"requested={requested} effective={effective}",
                file=sys.stderr,
            )
            remaining_irq_count += 1

        if remaining_irq_count == 0:
            print(f"IRQ 检查通过：没有 IRQ 使用隔离 CPU（{config.isolated_cpus}）。")
        else:
            print(
                f"IRQ 检查发现 {remaining_irq_count} 个残留；"
                "managed IRQ 可能无法在运行时迁移，请确认数量合理。",
                file=sys.stderr,
            )
        self.irq_setup_started = False

    def print_summary(self) -> None:
        print("\nNEMU 运行时 CPU 隔离设置完成。")
        print(f"  isolated CPU：{self.read_file('/sys/fs/cgroup/cpuset.cpus.isolated')}")
        print(f"  workqueue：{self.read_file('/sys/devices/virtual/workqueue/cpumask')}")
        print(f"  watchdog：{self.read_file('/proc/sys/kernel/watchdog_cpumask')}")
        print(f"  默认 IRQ mask：{self.read_file('/proc/irq/default_smp_affinity')}")
        print("现在可以执行 exit 退出 root shell；benchmark 必须以普通用户身份运行。")

    def execute(self) -> None:
        self.check_prerequisites()
        self.backup_state()
        self.create_cpuset()
        self.configure_frequency_and_watchdog()
        self.configure_irq()
        self.print_summary()


def main() -> int:
    try:
        cpu_input = parse_cpu_argument(sys.argv)
        if cpu_input is None:
            return 0
        config = load_runtime_config(cpu_input, require_housekeeping=True)
    except ArgumentError as exc:
        return exc.status

    setup = IsolationSetup(config)
    try:
        setup.execute()
    except SetupError as exc:
        return setup.report_failure(str(exc), exc.status)
    except subprocess.CalledProcessError as exc:
        return setup.report_failure(
            f"命令执行失败（退出状态 {exc.returncode}）：{' '.join(exc.cmd)}",
            exc.returncode or 1,
        )
    except OSError as exc:
        return setup.report_failure(f"操作失败：{exc}")
    return 0


if __name__ == "__main__":
    from _common import main_guard

    main_guard(main)
