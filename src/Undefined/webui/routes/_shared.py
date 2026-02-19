import ipaddress
import time
from pathlib import Path
from typing import Any, cast

from aiohttp import web

from ..core import BotProcessController, SessionStore

routes = web.RouteTableDef()

STATIC_DIR = Path(__file__).parent.parent / "static"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

SESSION_COOKIE = "undefined_webui"
TOKEN_COOKIE = "undefined_webui_token"
SESSION_TTL_SECONDS = 8 * 60 * 60
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_ATTEMPT_WINDOW = 5 * 60
LOGIN_BLOCK_SECONDS = 15 * 60

_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_BLOCKED_UNTIL: dict[str, float] = {}


def get_bot(request: web.Request) -> BotProcessController:
    return cast(BotProcessController, request.app["bot"])


def get_session_store(request: web.Request) -> SessionStore:
    return cast(SessionStore, request.app["session_store"])


def get_settings(request: web.Request) -> Any:
    return request.app["settings"]


def check_auth(request: web.Request) -> bool:
    sessions = get_session_store(request)
    token = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Auth-Token")
    return sessions.is_valid(token)


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
