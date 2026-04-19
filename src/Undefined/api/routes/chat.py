"""Chat route handlers extracted from the Runtime API application."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import Any, Awaitable, Callable

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _VIRTUAL_USER_ID,
    _WebUIVirtualSender,
    _build_chat_response_payload,
    _json_error,
    _sse_event,
    _to_bool,
)
from Undefined.attachments import (
    attachment_refs_to_xml,
    build_attachment_scope,
    register_message_attachments,
    render_message_with_pic_placeholders,
)
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.services.queue_manager import QUEUE_LANE_SUPERADMIN
from Undefined.utils.common import message_to_segments
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

_VIRTUAL_USER_NAME = "system"
_CHAT_SSE_KEEPALIVE_SECONDS = 10.0


async def run_webui_chat(
    ctx: RuntimeAPIContext,
    *,
    text: str,
    send_output: Callable[[int, str], Awaitable[None]],
) -> str:
    """Execute a single WebUI chat turn (command dispatch or AI ask)."""

    cfg = ctx.config_getter()
    permission_sender_id = int(cfg.superadmin_qq)
    webui_scope_key = build_attachment_scope(
        user_id=_VIRTUAL_USER_ID,
        request_type="private",
        webui_session=True,
    )
    input_segments = message_to_segments(text)
    registered_input = await register_message_attachments(
        registry=ctx.ai.attachment_registry,
        segments=input_segments,
        scope_key=webui_scope_key,
        resolve_image_url=ctx.onebot.get_image,
        get_forward_messages=ctx.onebot.get_forward_msg,
    )
    normalized_text = registered_input.normalized_text or text
    await ctx.history_manager.add_private_message(
        user_id=_VIRTUAL_USER_ID,
        text_content=normalized_text,
        display_name=_VIRTUAL_USER_NAME,
        user_name=_VIRTUAL_USER_NAME,
        attachments=registered_input.attachments,
    )

    command = ctx.command_dispatcher.parse_command(normalized_text)
    if command:
        await ctx.command_dispatcher.dispatch_private(
            user_id=_VIRTUAL_USER_ID,
            sender_id=permission_sender_id,
            command=command,
            send_private_callback=send_output,
            is_webui_session=True,
        )
        return "command"

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    attachment_xml = (
        f"\n{attachment_refs_to_xml(registered_input.attachments)}"
        if registered_input.attachments
        else ""
    )
    full_question = f"""<message sender="{escape_xml_attr(_VIRTUAL_USER_NAME)}" sender_id="{escape_xml_attr(_VIRTUAL_USER_ID)}" location="WebUI私聊" time="{escape_xml_attr(current_time)}">
 <content>{escape_xml_text(normalized_text)}</content>{attachment_xml}
 </message>

【WebUI 会话】
这是一条来自 WebUI 控制台的会话请求。
会话身份：虚拟用户 system(42)。
权限等级：superadmin（你可按最高管理权限处理）。
请正常进行私聊对话；如果需要结束会话，调用 end 工具。"""
    virtual_sender = _WebUIVirtualSender(
        _VIRTUAL_USER_ID, send_output, onebot=ctx.onebot
    )

    async def _get_recent_cb(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        return await get_recent_messages_prefer_local(
            chat_id=chat_id,
            msg_type=msg_type,
            start=start,
            end=end,
            onebot_client=ctx.onebot,
            history_manager=ctx.history_manager,
            bot_qq=cfg.bot_qq,
            attachment_registry=getattr(ctx.ai, "attachment_registry", None),
        )

    async with RequestContext(
        request_type="private",
        user_id=_VIRTUAL_USER_ID,
        sender_id=permission_sender_id,
    ) as rctx:
        ai_client = ctx.ai  # noqa: F841
        memory_storage = ctx.ai.memory_storage  # noqa: F841
        runtime_config = ctx.ai.runtime_config  # noqa: F841
        sender = virtual_sender  # noqa: F841
        history_manager = ctx.history_manager  # noqa: F841
        onebot_client = ctx.onebot  # noqa: F841
        scheduler = ctx.scheduler  # noqa: F841

        def send_message_callback(
            msg: str, reply_to: int | None = None
        ) -> Awaitable[None]:
            _ = reply_to
            return send_output(_VIRTUAL_USER_ID, msg)

        get_recent_messages_callback = _get_recent_cb  # noqa: F841
        get_image_url_callback = ctx.onebot.get_image  # noqa: F841
        get_forward_msg_callback = ctx.onebot.get_forward_msg  # noqa: F841
        resource_vars = dict(globals())
        resource_vars.update(locals())
        resources = collect_context_resources(resource_vars)
        for key, value in resources.items():
            if value is not None:
                rctx.set_resource(key, value)
        rctx.set_resource("queue_lane", QUEUE_LANE_SUPERADMIN)
        rctx.set_resource("webui_session", True)
        rctx.set_resource("webui_permission", "superadmin")

        result = await ctx.ai.ask(
            full_question,
            send_message_callback=send_message_callback,
            get_recent_messages_callback=get_recent_messages_callback,
            get_image_url_callback=get_image_url_callback,
            get_forward_msg_callback=get_forward_msg_callback,
            sender=sender,
            history_manager=history_manager,
            onebot_client=onebot_client,
            scheduler=scheduler,
            extra_context={
                "is_private_chat": True,
                "request_type": "private",
                "user_id": _VIRTUAL_USER_ID,
                "sender_name": _VIRTUAL_USER_NAME,
                "webui_session": True,
                "webui_permission": "superadmin",
            },
        )

    final_reply = str(result or "").strip()
    if final_reply:
        await send_output(_VIRTUAL_USER_ID, final_reply)

    return "chat"


async def chat_history_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    """Return recent WebUI chat history."""

    limit_raw = str(request.query.get("limit", "200") or "200").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 200
    limit = max(1, min(limit, 500))

    getter = getattr(ctx.history_manager, "get_recent_private", None)
    if not callable(getter):
        return _json_error("History manager not ready", status=503)

    records = getter(_VIRTUAL_USER_ID, limit)
    items: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        content = str(item.get("message", "")).strip()
        if not content:
            continue
        display_name = str(item.get("display_name", "")).strip().lower()
        role = "bot" if display_name == "bot" else "user"
        items.append(
            {
                "role": role,
                "content": content,
                "timestamp": str(item.get("timestamp", "") or "").strip(),
            }
        )

    return web.json_response(
        {
            "virtual_user_id": _VIRTUAL_USER_ID,
            "permission": "superadmin",
            "count": len(items),
            "items": items,
        }
    )


async def chat_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> web.StreamResponse:
    """Handle a WebUI chat request (non-streaming or SSE streaming)."""

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)

    text = str(body.get("message", "") or "").strip()
    if not text:
        return _json_error("message is required", status=400)

    stream = _to_bool(body.get("stream"))
    outputs: list[str] = []
    webui_scope_key = build_attachment_scope(
        user_id=_VIRTUAL_USER_ID,
        request_type="private",
        webui_session=True,
    )

    async def _capture_private_message(user_id: int, message: str) -> None:
        _ = user_id
        content = str(message or "").strip()
        if not content:
            return
        rendered = await render_message_with_pic_placeholders(
            content,
            registry=ctx.ai.attachment_registry,
            scope_key=webui_scope_key,
            strict=False,
        )
        if not rendered.delivery_text.strip():
            return
        outputs.append(rendered.delivery_text)
        await ctx.history_manager.add_private_message(
            user_id=_VIRTUAL_USER_ID,
            text_content=rendered.history_text,
            display_name="Bot",
            user_name="Bot",
            attachments=rendered.attachments,
        )

    if not stream:
        try:
            mode = await run_webui_chat(
                ctx, text=text, send_output=_capture_private_message
            )
        except Exception as exc:
            logger.exception("[RuntimeAPI] chat failed: %s", exc)
            return _json_error("Chat failed", status=502)
        return web.json_response(_build_chat_response_payload(mode, outputs))

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    message_queue: asyncio.Queue[str] = asyncio.Queue()

    async def _capture_private_message_stream(user_id: int, message: str) -> None:
        output_count = len(outputs)
        await _capture_private_message(user_id, message)
        if len(outputs) <= output_count:
            return
        content = outputs[-1].strip()
        if content:
            await message_queue.put(content)

    task = asyncio.create_task(
        run_webui_chat(ctx, text=text, send_output=_capture_private_message_stream)
    )
    mode = "chat"
    client_disconnected = False
    try:
        await response.write(
            _sse_event(
                "meta",
                {
                    "virtual_user_id": _VIRTUAL_USER_ID,
                    "permission": "superadmin",
                },
            )
        )

        while True:
            if request.transport is None or request.transport.is_closing():
                client_disconnected = True
                break
            if task.done() and message_queue.empty():
                break
            try:
                message = await asyncio.wait_for(
                    message_queue.get(),
                    timeout=_CHAT_SSE_KEEPALIVE_SECONDS,
                )
                await response.write(_sse_event("message", {"content": message}))
            except asyncio.TimeoutError:
                await response.write(b": keep-alive\n\n")

        if client_disconnected:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            return response

        mode = await task
        await response.write(
            _sse_event("done", _build_chat_response_payload(mode, outputs))
        )
    except asyncio.CancelledError:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise
    except (ConnectionResetError, RuntimeError):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    except Exception as exc:
        logger.exception("[RuntimeAPI] chat stream failed: %s", exc)
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        with suppress(Exception):
            await response.write(_sse_event("error", {"error": str(exc)}))
    finally:
        with suppress(Exception):
            await response.write_eof()

    return response
