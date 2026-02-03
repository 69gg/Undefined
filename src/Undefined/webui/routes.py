import logging
import json
import tomllib
from pathlib import Path

from aiohttp import web
from aiohttp.web_response import Response
from typing import cast, Any


from Undefined.config.loader import CONFIG_PATH

from .core import BotProcessController, SessionStore
from .utils import (
    read_config_source,
    validate_toml,
    validate_required_config,
    tail_file,
)

logger = logging.getLogger(__name__)

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
    token = request.cookies.get("undefined_webui_token")
    if not token:
        return False
    return get_session_store(request).is_valid(token)


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
    return web.Response(text=html, content_type="text/html")


@routes.post("/api/login")
async def login_handler(request: web.Request) -> Response:
    data = await request.json()
    password = data.get("password")
    settings = get_settings(request)

    if password == settings.password:
        token = get_session_store(request).create()
        resp = web.json_response({"success": True})
        resp.set_cookie(
            "undefined_webui_token", token, max_age=8 * 60 * 60, samesite="Strict"
        )
        return resp

    return web.json_response(
        {"success": False, "error": "Invalid password"}, status=401
    )


@routes.post("/api/logout")
async def logout_handler(request: web.Request) -> Response:
    token = request.cookies.get("undefined_webui_token")
    get_session_store(request).revoke(token)
    resp = web.json_response({"success": True})
    resp.del_cookie("undefined_webui_token")
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
