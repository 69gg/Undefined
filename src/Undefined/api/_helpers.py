"""Helper classes and utility functions for the Runtime API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.config import load_webui_settings
from Undefined.utils.cors import is_allowed_cors_origin, normalize_origin

logger = logging.getLogger(__name__)

_AUTH_HEADER = "X-Undefined-API-Key"
_VIRTUAL_USER_ID = 42


class _ToolInvokeExecutionTimeoutError(asyncio.TimeoutError):
    """由 Runtime API 工具调用超时包装器抛出的超时异常。"""


@dataclass
class _NagaRequestResult:
    payload_hash: str
    status: int
    payload: dict[str, Any]
    finished_at: float


class _WebUIVirtualSender:
    """将工具发送行为重定向到 WebUI 会话，不触发 OneBot 实际发送。"""

    def __init__(
        self,
        virtual_user_id: int,
        send_private_callback: Callable[[int, str], Awaitable[None]],
        onebot: Any = None,
    ) -> None:
        self._virtual_user_id = virtual_user_id
        self._send_private_callback = send_private_callback
        # 保留 onebot 属性，兼容依赖 sender.onebot 的工具读取能力。
        self.onebot = onebot

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
    ) -> int | None:
        _ = (
            user_id,
            auto_history,
            mark_sent,
            reply_to,
            preferred_temp_group_id,
            history_message,
        )
        await self._send_private_callback(self._virtual_user_id, message)
        return None

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        history_message: str | None = None,
    ) -> int | None:
        _ = (
            group_id,
            auto_history,
            history_prefix,
            mark_sent,
            reply_to,
            history_message,
        )
        await self._send_private_callback(self._virtual_user_id, message)
        return None

    async def send_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """将文件拷贝到 WebUI 缓存并发送文件卡片消息。"""
        _ = user_id, auto_history
        import shutil
        import uuid as _uuid
        from pathlib import Path as _Path

        from Undefined.utils.paths import WEBUI_FILE_CACHE_DIR, ensure_dir

        src = _Path(file_path)
        display_name = name or src.name
        file_id = _uuid.uuid4().hex
        dest_dir = ensure_dir(WEBUI_FILE_CACHE_DIR / file_id)
        dest = dest_dir / display_name

        def _copy_and_stat() -> int:
            shutil.copy2(src, dest)
            return dest.stat().st_size

        try:
            file_size = await asyncio.to_thread(_copy_and_stat)
        except OSError:
            file_size = 0

        message = f"[CQ:file,id={file_id},name={display_name},size={file_size}]"
        await self._send_private_callback(self._virtual_user_id, message)

    async def send_group_file(
        self,
        group_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """群文件在虚拟会话中同样重定向为文本消息。"""
        await self.send_private_file(group_id, file_path, name, auto_history)


def _json_error(message: str, status: int = 400) -> Response:
    return web.json_response({"error": message}, status=status)


def _apply_cors_headers(request: web.Request, response: web.StreamResponse) -> None:
    origin = normalize_origin(str(request.headers.get("Origin") or ""))
    settings = load_webui_settings()
    response.headers.setdefault("Vary", "Origin")
    response.headers.setdefault(
        "Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS"
    )
    response.headers.setdefault(
        "Access-Control-Allow-Headers",
        "Authorization, Content-Type, X-Undefined-API-Key",
    )
    response.headers.setdefault("Access-Control-Max-Age", "86400")
    if origin and is_allowed_cors_origin(
        origin,
        configured_host=str(settings.url or ""),
        configured_port=settings.port,
    ):
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")


def _optional_query_param(request: web.Request, key: str) -> str | None:
    raw = request.query.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text


def _parse_query_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text, text.replace("Z", "+00:00")]
    if "T" in text:
        candidates.append(text.replace("T", " "))
    for candidate in candidates:
        with suppress(ValueError):
            return datetime.fromisoformat(candidate)
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _build_chat_response_payload(mode: str, outputs: list[str]) -> dict[str, Any]:
    return {
        "mode": mode,
        "virtual_user_id": _VIRTUAL_USER_ID,
        "permission": "superadmin",
        "messages": outputs,
        "reply": "\n\n".join(outputs).strip(),
    }


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _mask_url(url: str) -> str:
    """保留 scheme + host，隐藏 path 细节。"""
    text = str(url or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlsplit(text)
    host = parsed.hostname or ""
    port_part = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}{port_part}/..."


def _naga_runtime_enabled(cfg: Any) -> bool:
    naga_cfg = getattr(cfg, "naga", None)
    return bool(getattr(cfg, "nagaagent_mode_enabled", False)) and bool(
        getattr(naga_cfg, "enabled", False)
    )


def _naga_routes_enabled(cfg: Any, naga_store: Any) -> bool:
    return _naga_runtime_enabled(cfg) and naga_store is not None


def _short_text_preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _naga_message_digest(
    *,
    bind_uuid: str,
    naga_id: str,
    target_qq: int,
    target_group: int,
    mode: str,
    message_format: str,
    content: str,
) -> str:
    raw = json.dumps(
        {
            "bind_uuid": bind_uuid,
            "naga_id": naga_id,
            "target_qq": target_qq,
            "target_group": target_group,
            "mode": mode,
            "format": message_format,
            "content": content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _parse_response_payload(response: Response) -> dict[str, Any]:
    text = response.text or ""
    if not text:
        return {}
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {"data": payload}


def _registry_summary(registry: Any) -> dict[str, Any]:
    """从 BaseRegistry 提取轻量摘要。"""
    if registry is None:
        return {"count": 0, "loaded": 0, "items": []}
    items: dict[str, Any] = getattr(registry, "_items", {})
    stats: dict[str, Any] = {}
    get_stats = getattr(registry, "get_stats", None)
    if callable(get_stats):
        stats = get_stats()
    summary_items: list[dict[str, Any]] = []
    for name, item in items.items():
        st = stats.get(name)
        entry: dict[str, Any] = {
            "name": name,
            "loaded": getattr(item, "loaded", False),
        }
        if st is not None:
            entry["calls"] = getattr(st, "count", 0)
            entry["success"] = getattr(st, "success", 0)
            entry["failure"] = getattr(st, "failure", 0)
        summary_items.append(entry)
    return {
        "count": len(items),
        "loaded": sum(1 for i in items.values() if getattr(i, "loaded", False)),
        "items": summary_items,
    }


def _validate_callback_url(url: str) -> str | None:
    """校验回调 URL，返回错误信息或 None 表示通过。

    拒绝非 HTTP(S) scheme，以及直接使用私有/回环 IP 字面量的 URL 以防止 SSRF。
    域名形式的 URL 放行（DNS 解析阶段不适合在校验函数中做阻塞调用）。
    """
    import ipaddress

    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()

    if scheme not in ("http", "https"):
        return "callback.url must use http or https"

    hostname = parsed.hostname or ""
    if not hostname:
        return "callback.url must include a hostname"

    # 仅检查 IP 字面量（如 http://127.0.0.1/、http://[::1]/、http://10.0.0.1/）
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # 域名形式，放行
    else:
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return "callback.url must not point to a private/loopback address"

    return None
