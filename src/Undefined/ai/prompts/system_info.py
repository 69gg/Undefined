"""跨平台系统信息采集与 Prompt 格式化。"""

from __future__ import annotations

import ipaddress
import os
import platform
import socket
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from Undefined import __version__

try:
    import psutil
except Exception:  # pragma: no cover - 仅在依赖缺失或平台导入失败时触发
    psutil = None

_BYTES_PER_GIB = 1024**3
_CPU_PERCENT_PRIMED = False


def _safe_call(func: Any, *args: Any, **kwargs: Any) -> Any | None:
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def _prime_cpu_percent() -> None:
    global _CPU_PERCENT_PRIMED
    if _CPU_PERCENT_PRIMED or psutil is None:
        return
    _safe_call(psutil.cpu_percent, interval=None)
    _CPU_PERCENT_PRIMED = True


_prime_cpu_percent()


def _format_bytes(value: float | int | None) -> str:
    if value is None:
        return "未知"
    gib = float(value) / _BYTES_PER_GIB
    if gib >= 1:
        return f"{gib:.2f} GiB"
    mib = float(value) / 1024**2
    return f"{mib:.1f} MiB"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "未知"


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "未知"
    total_seconds = max(0, int(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if not parts:
        parts.append(f"{seconds}秒")
    return "".join(parts)


def _format_timestamp(timestamp: float | int | None) -> str:
    if timestamp is None:
        return "未知"
    try:
        return datetime.fromtimestamp(float(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return "未知"


def _read_cpu_model() -> str:
    model = platform.processor().strip()
    if model:
        return model
    if hasattr(platform, "uname"):
        processor = str(platform.uname().processor or "").strip()
        if processor:
            return processor
    return "未知"


def _is_loopback_or_empty_address(address: str) -> bool:
    text = address.strip()
    if not text:
        return True
    try:
        parsed = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    return parsed.is_loopback or parsed.is_unspecified


def _iter_network_addresses() -> Iterable[str]:
    if psutil is None:
        return []
    addrs = _safe_call(psutil.net_if_addrs)
    if not isinstance(addrs, dict):
        return []

    lines: list[str] = []
    for name, items in sorted(addrs.items()):
        address_parts: list[str] = []
        for item in items:
            family = getattr(item, "family", None)
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            address = str(getattr(item, "address", "") or "").strip()
            if _is_loopback_or_empty_address(address):
                continue
            address_parts.append(address)
        if address_parts:
            lines.append(f"{name}: {', '.join(address_parts)}")
    return lines


def _iter_disk_lines(max_items: int = 12) -> Iterable[str]:
    if psutil is None:
        return []
    partitions = _safe_call(psutil.disk_partitions, all=False)
    if not isinstance(partitions, list):
        return []

    valid_lines: list[str] = []
    seen_mounts: set[str] = set()
    for part in partitions:
        mountpoint = str(getattr(part, "mountpoint", "") or "").strip()
        if not mountpoint or mountpoint in seen_mounts:
            continue
        seen_mounts.add(mountpoint)
        usage = _safe_call(psutil.disk_usage, mountpoint)
        if usage is None:
            continue
        filesystem = str(getattr(part, "fstype", "") or "未知")
        total = _format_bytes(getattr(usage, "total", None))
        used = _format_bytes(getattr(usage, "used", None))
        percent = _format_percent(getattr(usage, "percent", None))
        valid_lines.append(f"{mountpoint} ({filesystem}): {used}/{total}, {percent}")
    lines = valid_lines[:max_items]
    skipped_count = max(0, len(valid_lines) - max_items)
    if skipped_count:
        lines.append(f"... 其余 {skipped_count} 个分区已省略")
    return lines


def _build_os_line() -> str:
    platform_text = platform.platform(aliased=True, terse=False)
    machine = platform.machine() or "未知"
    return f"- OS: {platform_text}; 架构: {machine}"


def _build_runtime_line() -> str:
    python_version = platform.python_version()
    return f"- Runtime: Python {python_version}; Undefined {__version__}"


def _build_host_line() -> str:
    hostname = platform.node() or socket.gethostname() or "未知"
    return f"- Host: {hostname}"


def _build_cpu_line() -> str:
    logical = os.cpu_count()
    physical = None
    if psutil is not None:
        physical = _safe_call(psutil.cpu_count, logical=False)
        logical_psutil = _safe_call(psutil.cpu_count, logical=True)
        if isinstance(logical_psutil, int) and logical_psutil > 0:
            logical = logical_psutil
    model = _read_cpu_model()
    core_text = f"逻辑核 {logical or '未知'}"
    if isinstance(physical, int) and physical > 0:
        core_text = f"物理核 {physical}, {core_text}"
    return f"- CPU: {model}; {core_text}"


def _build_cpu_usage_line() -> str | None:
    if psutil is None:
        return None
    _prime_cpu_percent()
    usage = _safe_call(psutil.cpu_percent, interval=None)
    if usage is None:
        return None
    return f"- CPU 使用率: {_format_percent(usage)}"


def _build_memory_line() -> str | None:
    if psutil is None:
        return None
    mem = _safe_call(psutil.virtual_memory)
    if mem is None:
        return None
    return (
        "- 内存: "
        f"{_format_bytes(getattr(mem, 'used', None))}/"
        f"{_format_bytes(getattr(mem, 'total', None))}, "
        f"{_format_percent(getattr(mem, 'percent', None))}"
    )


def _build_swap_line() -> str | None:
    if psutil is None:
        return None
    swap = _safe_call(psutil.swap_memory)
    if swap is None:
        return None
    total = getattr(swap, "total", 0) or 0
    if int(total) <= 0:
        return "- Swap: 未配置"
    return (
        "- Swap: "
        f"{_format_bytes(getattr(swap, 'used', None))}/"
        f"{_format_bytes(total)}, "
        f"{_format_percent(getattr(swap, 'percent', None))}"
    )


def _build_disks_line() -> str | None:
    lines = list(_iter_disk_lines())
    if not lines:
        return None
    return "- 磁盘:\n  - " + "\n  - ".join(lines)


def _build_network_line() -> str | None:
    address_lines = list(_iter_network_addresses())
    io_text = ""
    if psutil is not None:
        counters = _safe_call(psutil.net_io_counters)
        if counters is not None:
            sent = _format_bytes(getattr(counters, "bytes_sent", None))
            recv = _format_bytes(getattr(counters, "bytes_recv", None))
            io_text = f"收发累计: sent={sent}, recv={recv}"
    if not address_lines and not io_text:
        return None
    parts: list[str] = []
    if io_text:
        parts.append(io_text)
    if address_lines:
        parts.append("地址:\n  - " + "\n  - ".join(address_lines))
    return "- 网络: " + "\n  ".join(parts)


def _build_process_line() -> str | None:
    if psutil is None:
        pid = os.getpid()
        return f"- 进程: PID {pid}"
    process = _safe_call(psutil.Process)
    if process is None:
        return None
    pid = os.getpid()
    create_time = _safe_call(process.create_time)
    runtime = (
        time.time() - float(create_time) if isinstance(create_time, float) else None
    )
    memory_info = _safe_call(process.memory_info)
    rss = getattr(memory_info, "rss", None) if memory_info is not None else None
    cpu_percent = _safe_call(process.cpu_percent, interval=None)
    parts = [
        f"PID {pid}",
        f"启动于 {_format_timestamp(create_time)}",
        f"运行 {_format_duration(runtime)}",
    ]
    if rss is not None:
        parts.append(f"RSS {_format_bytes(rss)}")
    if cpu_percent is not None:
        parts.append(f"CPU {_format_percent(cpu_percent)}")
    return "- 进程: " + "; ".join(parts)


def _build_uptime_line() -> str | None:
    if psutil is None:
        return None
    boot_time = _safe_call(psutil.boot_time)
    if not isinstance(boot_time, (int, float)):
        return None
    uptime = time.time() - float(boot_time)
    return f"- 系统启动: {_format_timestamp(boot_time)}; 已运行: {_format_duration(uptime)}"


def build_prompt_system_info(config: Any) -> str:
    """按配置采集并格式化当前系统信息。"""

    if not bool(getattr(config, "enabled", False)):
        return ""

    parts: list[str] = ["【当前系统信息】"]

    builders: list[tuple[str, Any]] = [
        ("show_os", _build_os_line),
        ("show_runtime", _build_runtime_line),
        ("show_host", _build_host_line),
        ("show_cpu", _build_cpu_line),
        ("show_cpu_usage", _build_cpu_usage_line),
        ("show_memory", _build_memory_line),
        ("show_swap", _build_swap_line),
        ("show_disks", _build_disks_line),
        ("show_network", _build_network_line),
        ("show_process", _build_process_line),
        ("show_uptime", _build_uptime_line),
    ]
    for flag_name, builder in builders:
        if not bool(getattr(config, flag_name, True)):
            continue
        line = _safe_call(builder)
        if isinstance(line, str) and line.strip():
            parts.append(line.strip())

    if len(parts) == 1:
        return ""
    parts.append("")
    parts.append(
        "注意：以上是当前运行主机的系统信息，可能随时间变化；"
        "回答系统状态、资源占用、运行环境相关问题时以此为准。"
    )
    return "\n".join(parts)


__all__ = ["build_prompt_system_info"]
