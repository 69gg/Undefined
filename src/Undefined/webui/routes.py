import asyncio
import logging
import json
import platform
import re
import tomllib
from pathlib import Path

from aiohttp import web
from aiohttp.web_response import Response
from typing import cast, Any


from Undefined.config.loader import CONFIG_PATH, load_toml_data
from Undefined.config import get_config_manager

from Undefined import __version__
from .core import BotProcessController, SessionStore
from .utils import (
    read_config_source,
    validate_toml,
    validate_required_config,
    tail_file,
    load_default_data,
    load_comment_map,
    merge_defaults,
    apply_patch,
    render_toml,
    sort_config,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "undefined_webui"
TOKEN_COOKIE = "undefined_webui_token"
SESSION_TTL_SECONDS = 8 * 60 * 60

# Use relative path from this file
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"

routes = web.RouteTableDef()


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
        total = sum(values)
        return idle, total
    except Exception:
        return None


async def _get_cpu_usage_percent() -> float | None:
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
    idle_delta = idle_2 - idle_1
    if total_delta <= 0:
        return None
    usage = (1 - idle_delta / total_delta) * 100
    return max(0.0, min(100.0, usage))


def _read_cpu_model() -> str:
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        for line in cpuinfo_path.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
    model = platform.processor()
    return model.strip() if model else "Unknown"


def _read_memory_info() -> tuple[float, float, float] | None:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return None
    total_kb = None
    available_kb = None
    for line in meminfo_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            total_kb = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available_kb = int(line.split()[1])
    if total_kb is None or available_kb is None:
        return None
    used_kb = max(0, total_kb - available_kb)
    total_gb = total_kb / 1024 / 1024
    used_gb = used_kb / 1024 / 1024
    usage = (used_kb / total_kb) * 100 if total_kb else 0.0
    return total_gb, used_gb, usage


def _resolve_log_path() -> Path:
    log_path = Path("logs/bot.log")
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                cfg = tomllib.load(f)
            path_str = cfg.get("logging", {}).get("file_path")
            if path_str:
                log_path = Path(path_str)
    except Exception:
        pass
    return log_path


def _resolve_webui_log_path() -> Path:
    return Path("logs/webui.log")


def _is_log_file(path: Path) -> bool:
    name = path.name
    if ".log" not in name:
        return False
    lowered = name.lower()
    if lowered.endswith((".tar", ".tar.gz", ".tgz")):
        return False
    return True


def _list_log_files(base_path: Path) -> list[Path]:
    files = [base_path]
    if base_path.parent.exists():
        prefix = f"{base_path.name}."
        for candidate in base_path.parent.glob(f"{base_path.name}.*"):
            suffix = candidate.name[len(prefix) :]
            if suffix.isdigit():
                files.append(candidate)

    def _sort_key(path: Path) -> tuple[int, str]:
        if path.name == base_path.name:
            return (0, "")
        match = re.search(r"\.([0-9]+)$", path.name)
        if match:
            return (1, match.group(1).zfill(6))
        return (2, path.name)

    return sorted(files, key=_sort_key)


def _list_all_log_files(log_dir: Path) -> list[Path]:
    if not log_dir.exists():
        return []
    files = [path for path in log_dir.glob("*.log*") if _is_log_file(path)]
    files.sort(key=lambda path: path.name)
    return files


def _resolve_log_file(base_path: Path, file_name: str | None) -> Path | None:
    if not file_name:
        return base_path
    for path in _list_log_files(base_path):
        if path.name == file_name:
            return path
    return None


def _resolve_any_log_file(log_dir: Path, file_name: str | None) -> Path | None:
    if not file_name:
        return None
    for path in _list_all_log_files(log_dir):
        if path.name == file_name:
            return path
    return None


# Global instances (injected via app, but for routes simplicity using global here/app context is better)
# For simplicity in this functional refactor, we will attach them to app['bot'] etc.


def get_bot(request: web.Request) -> BotProcessController:
    return cast(BotProcessController, request.app["bot"])


def get_session_store(request: web.Request) -> SessionStore:
    return cast(SessionStore, request.app["session_store"])


def get_settings(request: web.Request) -> Any:
    return request.app["settings"]


def check_auth(request: web.Request) -> bool:
    sessions = get_session_store(request)
    # Extract token from cookie or header
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        token = request.cookies.get(TOKEN_COOKIE)
    if not token:
        token = request.headers.get("X-Auth-Token")

    return sessions.is_valid(token)


@routes.get("/")
async def index_handler(request: web.Request) -> Response:
    # Serve the SPA HTML
    # We inject some initial state into the HTML to avoid an extra RTT
    settings = get_settings(request)

    html_file = TEMPLATE_DIR / "index.html"
    if not html_file.exists():
        return web.Response(text="Index template not found", status=500)

    html = html_file.read_text(encoding="utf-8")

    license_file = Path("LICENSE")
    license_text = (
        license_file.read_text(encoding="utf-8") if license_file.exists() else ""
    )

    lang = request.cookies.get("undefined_lang", "zh")
    theme = request.cookies.get("undefined_theme", "light")

    # Inject initial state
    initial_state = {
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
        "version": __version__,
        "license": license_text,
        "lang": lang,
        "theme": theme,
    }

    html = html.replace("__INITIAL_STATE__", json.dumps(initial_state))
    # Original used placeholders
    html = html.replace("__INITIAL_VIEW__", '"landing"')
    html = html.replace(
        "__DEFAULT_FLAG__", "true" if settings.using_default_password else "false"
    )
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/login")
async def login_handler(request: web.Request) -> Response:
    data = await request.json()
    password = data.get("password")
    settings = get_settings(request)

    if password == settings.password:
        token = get_session_store(request).create()
        resp = web.json_response({"success": True, "token": token})
        # Set both cookies for maximum compatibility
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="Lax",
            max_age=SESSION_TTL_SECONDS,
        )
        resp.set_cookie(
            TOKEN_COOKIE,
            token,
            httponly=False,
            samesite="Lax",
            max_age=SESSION_TTL_SECONDS,
        )
        return resp

    return web.json_response(
        {"success": False, "error": "Invalid password"}, status=401
    )


@routes.get("/api/session")
async def session_handler(request: web.Request) -> Response:
    settings = get_settings(request)
    authenticated = check_auth(request)
    summary = (
        f"{settings.url}:{settings.port} | {'ready' if authenticated else 'locked'}"
    )
    payload = {
        "authenticated": authenticated,
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
        "config_path": str(CONFIG_PATH),
        "summary": summary,
    }
    return web.json_response(payload)


@routes.post("/api/logout")
async def logout_handler(request: web.Request) -> Response:
    token = (
        request.cookies.get(SESSION_COOKIE)
        or request.cookies.get(TOKEN_COOKIE)
        or request.headers.get("X-Auth-Token")
    )
    get_session_store(request).revoke(token)
    resp = web.json_response({"success": True})
    resp.del_cookie(SESSION_COOKIE)
    resp.del_cookie(TOKEN_COOKIE)
    return resp


@routes.get("/api/status")
async def status_handler(request: web.Request) -> Response:
    bot = get_bot(request)
    return web.json_response(bot.status())


@routes.post("/api/bot/{action}")
async def bot_action_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    action = request.match_info["action"]
    bot = get_bot(request)

    if action == "start":
        status = await bot.start()
        return web.json_response(status)
    elif action == "stop":
        status = await bot.stop()
        return web.json_response(status)

    return web.json_response({"error": "Invalid action"}, status=400)


@routes.get("/api/config")
async def get_config_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    return web.json_response(read_config_source())


@routes.post("/api/config")
async def save_config_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = await request.json()
    content = data.get("content")

    if not content:
        return web.json_response({"error": "No content provided"}, status=400)

    valid, msg = validate_toml(content)
    if not valid:
        return web.json_response({"success": False, "error": msg}, status=400)

    try:
        CONFIG_PATH.write_text(content, encoding="utf-8")
        get_config_manager().reload()
        # Validate logic requirements (optional, warn but save is ok if syntax is valid)
        logic_valid, logic_msg = validate_required_config()
        return web.json_response(
            {
                "success": True,
                "message": "Saved",
                "warning": None if logic_valid else logic_msg,
            }
        )
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.get("/api/config/summary")
async def config_summary_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = load_toml_data()
    defaults = load_default_data()
    summary = merge_defaults(defaults, data)
    ordered = sort_config(summary)
    comments = load_comment_map()
    return web.json_response({"data": ordered, "comments": comments})


@routes.post("/api/patch")
async def config_patch_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    patch = body.get("patch")
    if not isinstance(patch, dict):
        return web.json_response({"error": "Invalid payload"}, status=400)

    source = read_config_source()
    try:
        data = tomllib.loads(source["content"]) if source["content"].strip() else {}
    except tomllib.TOMLDecodeError as exc:
        return web.json_response({"error": f"TOML parse error: {exc}"}, status=400)

    if not isinstance(data, dict):
        data = {}

    patched = apply_patch(data, patch)
    rendered = render_toml(patched)
    CONFIG_PATH.write_text(rendered, encoding="utf-8")
    get_config_manager().reload()
    validation_ok, validation_msg = validate_required_config()

    return web.json_response(
        {
            "success": True,
            "message": "Saved",
            "warning": None if validation_ok else validation_msg,
        }
    )


@routes.get("/api/logs")
async def logs_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    lines = int(request.query.get("lines", "200"))
    lines = max(1, min(lines, 2000))
    log_type = request.query.get("type", "bot")
    file_name = request.query.get("file")
    if log_type == "webui":
        log_path = _resolve_webui_log_path()
        target_path = _resolve_log_file(log_path, file_name)
    elif log_type == "all":
        target_path = _resolve_any_log_file(Path("logs"), file_name)
    else:
        log_path = _resolve_log_path()
        target_path = _resolve_log_file(log_path, file_name)
    if target_path is None:
        return web.json_response({"error": "Log file not found"}, status=404)
    content = tail_file(target_path, lines)
    return web.Response(text=content)


@routes.get("/api/logs/files")
async def logs_files_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    log_type = request.query.get("type", "bot")
    if log_type == "webui":
        log_path = _resolve_webui_log_path()
        files_list = _list_log_files(log_path)
        current_name = log_path.name
    elif log_type == "all":
        log_path = Path("logs")
        files_list = _list_all_log_files(log_path)
        current_name = ""
    else:
        log_path = _resolve_log_path()
        files_list = _list_log_files(log_path)
        current_name = log_path.name

    files: list[dict[str, Any]] = []
    for path in files_list:
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = int(stat.st_mtime)
            exists = True
        except FileNotFoundError:
            size = 0
            mtime = 0
            exists = False
        files.append(
            {
                "name": path.name,
                "size": size,
                "modified": mtime,
                "current": path.name == current_name,
                "exists": exists,
            }
        )
    return web.json_response({"files": files, "current": current_name})


@routes.get("/api/logs/stream")
async def logs_stream_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    lines = int(request.query.get("lines", "200"))
    lines = max(1, min(lines, 2000))
    log_type = request.query.get("type", "bot")
    if log_type == "all":
        return web.json_response(
            {"error": "Streaming only supports bot/webui logs"}, status=400
        )
    log_path = _resolve_webui_log_path() if log_type == "webui" else _resolve_log_path()
    file_name = request.query.get("file")
    if file_name and file_name != log_path.name:
        return web.json_response(
            {"error": "Streaming only supports current log"}, status=400
        )

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    resp = web.StreamResponse(status=200, reason="OK", headers=headers)
    await resp.prepare(request)

    last_payload: str | None = None
    try:
        while True:
            if request.transport is None or request.transport.is_closing():
                break
            payload = tail_file(log_path, lines)
            if payload != last_payload:
                data = "\n".join(f"data: {line}" for line in payload.splitlines())
                await resp.write((data + "\n\n").encode("utf-8"))
                last_payload = payload
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.debug("[WebUI] logs stream cancelled")
    except (ConnectionResetError, RuntimeError):
        pass
    finally:
        try:
            await resp.write_eof()
        except Exception:
            pass

    return resp


@routes.get("/api/system")
async def system_info_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    cpu_usage = await _get_cpu_usage_percent()
    memory_info = _read_memory_info()

    payload = {
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
