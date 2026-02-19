import tomllib

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.config.loader import CONFIG_PATH, DEFAULT_WEBUI_PASSWORD
from Undefined.config import get_config_manager, load_webui_settings
from ._shared import (
    routes,
    SESSION_COOKIE,
    TOKEN_COOKIE,
    SESSION_TTL_SECONDS,
    get_settings,
    get_session_store,
    check_auth,
    _get_client_ip,
    _is_local_request,
    _check_login_rate_limit,
    _record_login_failure,
    _clear_login_failures,
)
from ..utils import read_config_source, apply_patch, render_toml


@routes.post("/api/login")
async def login_handler(request: web.Request) -> Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON"}, status=400
        )

    password = data.get("password")
    settings = get_settings(request)

    if settings.using_default_password:
        return web.json_response(
            {
                "success": False,
                "error": "Default password is disabled. Please update it first.",
                "code": "default_password",
            },
            status=403,
        )

    client_ip = _get_client_ip(request)
    allowed, retry_after = _check_login_rate_limit(client_ip)
    if not allowed:
        return web.json_response(
            {
                "success": False,
                "error": "Too many login attempts. Please try again later.",
                "retry_after": retry_after,
                "code": "rate_limited",
            },
            status=429,
        )

    if password == settings.password:
        _clear_login_failures(client_ip)
        token = get_session_store(request).create()
        resp = web.json_response({"success": True})
        resp.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="Lax",
            max_age=SESSION_TTL_SECONDS,
        )
        return resp

    ok, block_seconds = _record_login_failure(client_ip)
    if not ok:
        return web.json_response(
            {
                "success": False,
                "error": "Too many login attempts. Please try again later.",
                "retry_after": block_seconds,
                "code": "rate_limited",
            },
            status=429,
        )
    return web.json_response(
        {"success": False, "error": "Invalid password"}, status=401
    )


@routes.get("/api/session")
async def session_handler(request: web.Request) -> Response:
    settings = get_settings(request)
    authenticated = check_auth(request)
    summary = f"{settings.url}:{settings.port} | ready" if authenticated else "locked"
    return web.json_response(
        {
            "authenticated": authenticated,
            "using_default_password": settings.using_default_password,
            "config_exists": settings.config_exists,
            "summary": summary,
        }
    )


@routes.post("/api/logout")
async def logout_handler(request: web.Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Auth-Token")
    get_session_store(request).revoke(token)
    resp = web.json_response({"success": True})
    resp.del_cookie(SESSION_COOKIE)
    resp.del_cookie(TOKEN_COOKIE)
    return resp


@routes.post("/api/password")
async def password_handler(request: web.Request) -> Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON"}, status=400
        )

    current_password = str(data.get("current_password") or "").strip()
    new_password = str(data.get("new_password") or "").strip()
    settings = get_settings(request)
    authenticated = check_auth(request)

    if not authenticated:
        if not settings.using_default_password:
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )
        if not _is_local_request(request):
            return web.json_response(
                {
                    "success": False,
                    "error": "Password change requires local access when using default password.",
                    "code": "local_required",
                },
                status=403,
            )

    if not current_password or current_password != settings.password:
        return web.json_response(
            {"success": False, "error": "Current password is incorrect."}, status=400
        )
    if not new_password:
        return web.json_response(
            {"success": False, "error": "New password is required."}, status=400
        )
    if new_password == settings.password:
        return web.json_response(
            {"success": False, "error": "New password must be different."}, status=400
        )
    if new_password == DEFAULT_WEBUI_PASSWORD:
        return web.json_response(
            {"success": False, "error": "New password cannot be the default value."},
            status=400,
        )

    source = read_config_source()
    try:
        data_dict = (
            tomllib.loads(source["content"]) if source["content"].strip() else {}
        )
    except tomllib.TOMLDecodeError as exc:
        return web.json_response(
            {"success": False, "error": f"TOML parse error: {exc}"}, status=400
        )
    if not isinstance(data_dict, dict):
        data_dict = {}

    patched = apply_patch(data_dict, {"webui.password": new_password})
    CONFIG_PATH.write_text(render_toml(patched), encoding="utf-8")
    get_config_manager().reload()
    request.app["settings"] = load_webui_settings()
    get_session_store(request).clear()

    resp = web.json_response({"success": True, "message": "Password updated"})
    resp.del_cookie(SESSION_COOKIE)
    resp.del_cookie(TOKEN_COOKIE)
    return resp
