import ipaddress
import time
from pathlib import Path
from typing import Any

from aiohttp import web

from Undefined.config import WebUISettings
from ..core import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    BotProcessController,
    SessionStore,
)

routes = web.RouteTableDef()

STATIC_DIR = Path(__file__).parent.parent / "static"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

BOT_APP_KEY = web.AppKey("bot", BotProcessController)
SESSION_STORE_APP_KEY = web.AppKey("session_store", SessionStore)
SETTINGS_APP_KEY = web.AppKey("settings", WebUISettings)
REDIRECT_TO_CONFIG_ONCE_APP_KEY = web.AppKey("redirect_to_config_once", bool)

SESSION_COOKIE = "undefined_webui"
TOKEN_COOKIE = "undefined_webui_token"
SESSION_TTL_SECONDS = 8 * 60 * 60
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW = 5 * 60
LOGIN_BLOCK_SECONDS = 15 * 60

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_BLOCKED_UNTIL: dict[str, float] = {}


def get_bot(request: web.Request) -> BotProcessController:
    return request.app[BOT_APP_KEY]


def get_session_store(request: web.Request) -> SessionStore:
    return request.app[SESSION_STORE_APP_KEY]


def get_settings(request: web.Request) -> WebUISettings:
    return request.app[SETTINGS_APP_KEY]


def get_bearer_token(request: web.Request) -> str | None:
    auth_header = str(request.headers.get("Authorization") or "").strip()
    if not auth_header:
        return None
    prefix = "bearer "
    if auth_header.lower().startswith(prefix):
        token = auth_header[len(prefix) :].strip()
        return token or None
    return None


def get_auth_token(request: web.Request) -> str | None:
    return (
        get_bearer_token(request)
        or request.cookies.get(SESSION_COOKIE)
        or request.headers.get("X-Auth-Token")
    )


def get_auth_tokens(request: web.Request) -> list[str]:
    tokens = [
        get_bearer_token(request),
        request.cookies.get(SESSION_COOKIE),
        request.headers.get("X-Auth-Token"),
    ]
    result: list[str] = []
    for token in tokens:
        text = str(token or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def get_refresh_token(
    request: web.Request, payload: dict[str, Any] | None = None
) -> str | None:
    if payload is not None:
        value = payload.get("refresh_token") or payload.get("refreshToken")
        text = str(value or "").strip()
        if text:
            return text
    return request.headers.get("X-Refresh-Token") or get_bearer_token(request)


def check_auth(request: web.Request) -> bool:
    sessions = get_session_store(request)
    for token in get_auth_tokens(request):
        if sessions.is_valid(token, allowed_kinds={"session", "access"}):
            return True
    return False


def get_valid_auth_token(request: web.Request) -> str | None:
    sessions = get_session_store(request)
    for token in get_auth_tokens(request):
        if sessions.is_valid(token, allowed_kinds={"session", "access"}):
            return token
    return None


def auth_capabilities() -> dict[str, Any]:
    return {
        "cookie_supported": True,
        "bearer_supported": True,
        "access_token_ttl_seconds": ACCESS_TOKEN_TTL_SECONDS,
        "refresh_token_ttl_seconds": REFRESH_TOKEN_TTL_SECONDS,
    }


def _get_client_ip(request: web.Request) -> str:
    if request.remote:
        return request.remote
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    return "unknown"


def _is_loopback_address(addr: str) -> bool:
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def _is_local_request(request: web.Request) -> bool:
    return _is_loopback_address(_get_client_ip(request))


def _check_login_rate_limit(client_ip: str) -> tuple[bool, int]:
    now = time.time()
    blocked_until = _LOGIN_BLOCKED_UNTIL.get(client_ip, 0)
    if blocked_until > now:
        return False, int(blocked_until - now)
    attempts = [
        ts
        for ts in _LOGIN_ATTEMPTS.get(client_ip, [])
        if now - ts <= LOGIN_ATTEMPT_WINDOW
    ]
    _LOGIN_ATTEMPTS[client_ip] = attempts
    return True, 0


def _record_login_failure(client_ip: str) -> tuple[bool, int]:
    now = time.time()
    attempts = [
        ts
        for ts in _LOGIN_ATTEMPTS.get(client_ip, [])
        if now - ts <= LOGIN_ATTEMPT_WINDOW
    ]
    attempts.append(now)
    if len(attempts) >= LOGIN_ATTEMPT_LIMIT:
        _LOGIN_ATTEMPTS.pop(client_ip, None)
        _LOGIN_BLOCKED_UNTIL[client_ip] = now + LOGIN_BLOCK_SECONDS
        return False, LOGIN_BLOCK_SECONDS
    _LOGIN_ATTEMPTS[client_ip] = attempts
    return True, 0


def _clear_login_failures(client_ip: str) -> None:
    _LOGIN_ATTEMPTS.pop(client_ip, None)
    _LOGIN_BLOCKED_UNTIL.pop(client_ip, None)
