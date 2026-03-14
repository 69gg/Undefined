import asyncio
import platform
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout
from aiohttp import web
from aiohttp.web_response import Response

from Undefined import __version__
from Undefined.config import get_config
from ._shared import auth_capabilities, routes, check_auth
from ..utils import load_bootstrap_probe_data

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    _PSUTIL_AVAILABLE = False

_CPU_PERCENT_PRIMED = False


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, value))


def _read_cpu_times() -> tuple[int, int] | None:
    try:
        stat_path = Path("/proc/stat")
        if not stat_path.exists():
            return None
        first_line = stat_path.read_text(encoding="utf-8").splitlines()[0]
        if not first_line.startswith("cpu "):
            return None
        parts = first_line.split()[1:]
        values = [int(p) for p in parts]
        if len(values) < 4:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return idle, sum(values)
    except Exception:
        return None


async def _get_cpu_usage_percent() -> float | None:
    global _CPU_PERCENT_PRIMED
    if _PSUTIL_AVAILABLE and psutil is not None:
        try:
            usage = psutil.cpu_percent(interval=None)
            if not _CPU_PERCENT_PRIMED:
                _CPU_PERCENT_PRIMED = True
                await asyncio.sleep(0.12)
                usage = psutil.cpu_percent(interval=None)
            return _clamp_percent(float(usage))
        except Exception:
            pass
    first = _read_cpu_times()
    if not first:
        return None
    idle_1, total_1 = first
    await asyncio.sleep(0.15)
    second = _read_cpu_times()
    if not second:
        return None
    idle_2, total_2 = second
    total_delta = total_2 - total_1
    if total_delta <= 0:
        return None
    return _clamp_percent((1 - (idle_2 - idle_1) / total_delta) * 100)


def _read_cpu_model() -> str:
    model = platform.processor()
    if model and model.strip():
        return model.strip()
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                parts = line.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    return parts[1].strip()
    return "Unknown"


def _read_memory_info() -> tuple[float, float, float] | None:
    if _PSUTIL_AVAILABLE and psutil is not None:
        try:
            mem = psutil.virtual_memory()
            return (
                float(mem.total) / 1024**3,
                float(mem.used) / 1024**3,
                _clamp_percent(float(mem.percent)),
            )
        except Exception:
            pass
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None
    total_kb = available_kb = None
    for line in meminfo_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available_kb = int(line.split()[1])
    if total_kb is None or available_kb is None:
        return None
    used_kb = max(0, total_kb - available_kb)
    return (
        total_kb / 1024**2,
        used_kb / 1024**2,
        (used_kb / total_kb * 100 if total_kb else 0.0),
    )


async def _runtime_health_status() -> tuple[bool, bool, str]:
    cfg = get_config(strict=False)
    if not bool(cfg.api.enabled):
        return False, False, "disabled"
    url = f"{cfg.api.loopback_url}/health"
    try:
        timeout = ClientTimeout(total=3.0)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                return True, resp.status < 500, f"HTTP {resp.status}"
    except Exception as exc:
        return True, False, str(exc)


def _bootstrap_advice(data: dict[str, object]) -> list[str]:
    advice: list[str] = []
    if not bool(data.get("config_exists")):
        advice.append("config.toml 缺失，建议先在控制台补齐基础配置。")
    if not bool(data.get("toml_valid")):
        advice.append("配置文件存在 TOML 语法错误，请先修复语法。")
    if (
        bool(data.get("toml_valid"))
        and bool(data.get("config_exists"))
        and not bool(data.get("config_valid"))
    ):
        error = str(data.get("validation_error") or "").strip()
        advice.append(error or "配置尚未通过严格校验，保存修复后即可启动 Bot。")
    if bool(data.get("using_default_password")):
        advice.append("默认 WebUI 密码已禁用，请先设置新密码后再继续。")
    if not advice:
        advice.append("管理入口已就绪，可继续编辑配置、查看日志或启动 Bot。")
    return advice


@routes.get("/api/v1/management/probes/bootstrap")
async def bootstrap_probe_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    bootstrap = load_bootstrap_probe_data()
    runtime_enabled, runtime_reachable, runtime_detail = await _runtime_health_status()
    payload = {
        **bootstrap,
        "runtime_enabled": runtime_enabled,
        "runtime_reachable": runtime_reachable,
        "runtime_detail": runtime_detail,
        "auth_mode": "token" if request.headers.get("Authorization") else "cookie",
        "management_url": f"{request.scheme}://{request.host}",
    }
    payload["advice"] = _bootstrap_advice(payload)
    return web.json_response(payload)


@routes.get("/api/v1/management/probes/capabilities")
async def capabilities_probe_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    runtime_enabled, runtime_reachable, runtime_detail = await _runtime_health_status()
    return web.json_response(
        {
            "management_api_v1": True,
            "runtime_proxy": True,
            "bootstrap_probe": True,
            "desktop_app": True,
            "android_app": True,
            "auth": auth_capabilities(),
            "config": {
                "read": True,
                "write": True,
                "validate": True,
                "sync_template": True,
            },
            "logs": {"read": True, "stream": True},
            "bot": {
                "status": True,
                "start": True,
                "stop": True,
                "update_restart": True,
            },
            "runtime": {
                "enabled": runtime_enabled,
                "reachable": runtime_reachable,
                "detail": runtime_detail,
            },
        }
    )


@routes.get("/api/v1/management/system")
@routes.get("/api/system")
async def system_info_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    cpu_usage = await _get_cpu_usage_percent()
    memory_info = _read_memory_info()
    payload: dict[str, object] = {
        "cpu_model": _read_cpu_model(),
        "cpu_usage_percent": None if cpu_usage is None else round(cpu_usage, 1),
        "memory_total_gb": None,
        "memory_used_gb": None,
        "memory_usage_percent": None,
        "system_version": platform.platform(),
        "system_release": platform.release(),
        "system_arch": platform.machine(),
        "python_version": platform.python_version(),
        "undefined_version": __version__,
    }
    if memory_info:
        total_gb, used_gb, usage = memory_info
        payload["memory_total_gb"] = round(total_gb, 2)
        payload["memory_used_gb"] = round(used_gb, 2)
        payload["memory_usage_percent"] = round(usage, 1)
    return web.json_response(payload)
