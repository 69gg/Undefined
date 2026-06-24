from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

from Undefined.ai.prompts import system_info
from Undefined.ai.prompts.system_info import build_prompt_system_info


def _enabled_config(**overrides: bool) -> SimpleNamespace:
    values: dict[str, bool] = {
        "enabled": True,
        "show_os": True,
        "show_runtime": True,
        "show_host": True,
        "show_cpu": True,
        "show_cpu_usage": True,
        "show_memory": True,
        "show_swap": True,
        "show_disks": True,
        "show_network": True,
        "show_process": True,
        "show_uptime": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeProcess:
    def create_time(self) -> float:
        return 999_940.0

    def memory_info(self) -> SimpleNamespace:
        return SimpleNamespace(rss=256 * 1024 * 1024)

    def cpu_percent(self, interval: float | None = None) -> float:
        _ = interval
        return 1.5


class _FakePsutil:
    AF_INET = socket.AF_INET
    AF_INET6 = socket.AF_INET6

    def cpu_count(self, logical: bool = True) -> int:
        return 16 if logical else 8

    def cpu_percent(self, interval: float | None = None) -> float:
        _ = interval
        return 12.3

    def virtual_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            total=32 * 1024**3,
            used=8 * 1024**3,
            percent=25.0,
        )

    def swap_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            total=4 * 1024**3,
            used=1024**3,
            percent=25.0,
        )

    def disk_partitions(self, all: bool = False) -> list[SimpleNamespace]:
        _ = all
        return [
            SimpleNamespace(mountpoint="/", fstype="ext4"),
            SimpleNamespace(mountpoint="/data", fstype="xfs"),
        ]

    def disk_usage(self, mountpoint: str) -> SimpleNamespace:
        _ = mountpoint
        return SimpleNamespace(
            total=100 * 1024**3,
            used=40 * 1024**3,
            percent=40.0,
        )

    def net_if_addrs(self) -> dict[str, list[SimpleNamespace]]:
        return {
            "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
            "eth0": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.20"),
                SimpleNamespace(family=socket.AF_INET6, address="fe80::1%eth0"),
            ],
        }

    def net_io_counters(self) -> SimpleNamespace:
        return SimpleNamespace(bytes_sent=1024**3, bytes_recv=2 * 1024**3)

    def Process(self) -> _FakeProcess:
        return _FakeProcess()

    def boot_time(self) -> float:
        return 900_000.0


def test_build_prompt_system_info_returns_empty_when_disabled() -> None:
    assert build_prompt_system_info(SimpleNamespace(enabled=False)) == ""
    assert build_prompt_system_info(None) == ""


def test_build_prompt_system_info_includes_enabled_sections(
    monkeypatch: Any,
) -> None:
    fake_psutil = _FakePsutil()
    monkeypatch.setattr(system_info, "psutil", fake_psutil)
    monkeypatch.setattr(
        system_info, "_build_os_line", lambda: "- OS: Linux-6; 架构: x86_64"
    )
    monkeypatch.setattr(
        system_info,
        "_build_runtime_line",
        lambda: "- Runtime: Python 3.12.0; Undefined test",
    )
    monkeypatch.setattr(system_info, "_build_host_line", lambda: "- Host: bot-host")
    monkeypatch.setattr(system_info, "_read_cpu_model", lambda: "Test CPU")

    text = build_prompt_system_info(_enabled_config())

    assert "【当前系统信息】" in text
    assert "- OS: Linux-6; 架构: x86_64" in text
    assert "- Runtime: Python 3.12.0; Undefined" in text
    assert "- Host: bot-host" in text
    assert "- CPU: Test CPU; 物理核 8, 逻辑核 16" in text
    assert "- CPU 使用率: 12.3%" in text
    assert "- 内存: 8.00 GiB/32.00 GiB, 25.0%" in text
    assert "- Swap: 1.00 GiB/4.00 GiB, 25.0%" in text
    assert "/ (ext4): 40.00 GiB/100.00 GiB, 40.0%" in text
    assert "eth0: 192.168.1.20, fe80::1%eth0" in text
    assert "127.0.0.1" not in text
    assert "- 进程: PID" in text
    assert "RSS 256.0 MiB" in text
    assert "- 系统启动:" in text


def test_build_prompt_system_info_respects_section_switches(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(system_info, "psutil", _FakePsutil())
    monkeypatch.setattr(
        system_info, "_build_os_line", lambda: "- OS: Linux-6; 架构: x86_64"
    )
    monkeypatch.setattr(
        system_info,
        "_build_runtime_line",
        lambda: "- Runtime: Python 3.12.0; Undefined test",
    )
    monkeypatch.setattr(system_info, "_build_host_line", lambda: "- Host: bot-host")
    monkeypatch.setattr(system_info, "_read_cpu_model", lambda: "Test CPU")

    text = build_prompt_system_info(
        _enabled_config(show_network=False, show_disks=False, show_process=False)
    )

    assert "【当前系统信息】" in text
    assert "- 网络:" not in text
    assert "- 磁盘:" not in text
    assert "- 进程:" not in text
    assert "- CPU:" in text


def test_build_prompt_system_info_skips_failed_sections(monkeypatch: Any) -> None:
    class BrokenPsutil(_FakePsutil):
        def virtual_memory(self) -> SimpleNamespace:
            raise RuntimeError("boom")

        def disk_partitions(self, all: bool = False) -> list[SimpleNamespace]:
            _ = all
            raise RuntimeError("boom")

    monkeypatch.setattr(system_info, "psutil", BrokenPsutil())
    monkeypatch.setattr(
        system_info, "_build_os_line", lambda: "- OS: Linux-6; 架构: x86_64"
    )
    monkeypatch.setattr(
        system_info,
        "_build_runtime_line",
        lambda: "- Runtime: Python 3.12.0; Undefined test",
    )
    monkeypatch.setattr(system_info, "_build_host_line", lambda: "- Host: bot-host")
    monkeypatch.setattr(system_info, "_read_cpu_model", lambda: "Test CPU")

    text = build_prompt_system_info(_enabled_config())

    assert "【当前系统信息】" in text
    assert "- 内存:" not in text
    assert "- 磁盘:" not in text
    assert "- CPU:" in text
