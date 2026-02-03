import logging
import json
import tomllib
from pathlib import Path

from aiohttp import web
from aiohttp.web_response import Response
from typing import cast, Any


from Undefined.config.loader import CONFIG_PATH, load_toml_data

from .core import BotProcessController, SessionStore
from .utils import (
    read_config_source,
    validate_toml,
    validate_required_config,
    tail_file,
    load_default_data,
    merge_defaults,
    apply_patch,
    render_toml,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "undefined_webui"
TOKEN_COOKIE = "undefined_webui_token"
SESSION_TTL_SECONDS = 8 * 60 * 60

# Use relative path from this file
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE_DIR = Path(__file__).parent / "templates"

routes = web.RouteTableDef()

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

    # Inject initial state
    initial_state = {
        "using_default_password": settings.using_default_password,
        "config_exists": settings.config_exists,
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
    return web.json_response({"data": summary})


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
    # Optional: check auth if sensitive
    # if not check_auth(request): return ...

    lines = int(request.query.get("lines", "200"))
    # Load log path from config or default
    # For now, simplistic reading. Ideally, read from loaded Config.
    # Assuming standard log path or parsing config.toml again (expensive)
    # Let's simple-parse config.toml for log path or use default
    log_path = Path("logs/bot.log")  # Default

    # Try to peek config
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "rb") as f:
                cfg = tomllib.load(f)
                path_str = cfg.get("logging", {}).get("file_path")
                if path_str:
                    log_path = Path(path_str)
    except Exception:
        pass

    content = tail_file(log_path, lines)
    return web.Response(text=content)
