"""Chat route handlers extracted from the Runtime API application."""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any, Awaitable, Callable
from uuid import uuid4

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
_CHAT_JOB_EVENT_BUFFER_LIMIT = 1000
_PREVIEW_LIMIT = 800


@dataclass
class ChatJobEvent:
    seq: int
    event: str
    payload: dict[str, Any]


@dataclass
class ChatJob:
    job_id: str
    text: str
    created_at: float
    updated_at: float
    status: str = "queued"
    mode: str = "chat"
    outputs: list[str] = field(default_factory=list)
    events: list[ChatJobEvent] = field(default_factory=list)
    next_seq: int = 1
    task: asyncio.Task[None] | None = None
    error: str = ""
    done: asyncio.Event = field(default_factory=asyncio.Event)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_seq": self.next_seq - 1,
            "error": self.error or None,
            "reply": "\n\n".join(self.outputs).strip(),
            "messages": list(self.outputs),
        }


class ChatJobManager:
    def __init__(self, ctx: RuntimeAPIContext) -> None:
        self._ctx = ctx
        self._jobs: dict[str, ChatJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, text: str) -> ChatJob:
        now = time.time()
        job = ChatJob(
            job_id=uuid4().hex,
            text=text,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._jobs[job.job_id] = job
        await self._append_event(
            job,
            "meta",
            {
                "job_id": job.job_id,
                "virtual_user_id": _VIRTUAL_USER_ID,
                "permission": "superadmin",
            },
        )
        job.task = asyncio.create_task(self._run_job(job), name=f"webchat:{job.job_id}")
        return job

    async def get_job(self, job_id: str) -> ChatJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def get_active_job(self) -> ChatJob | None:
        async with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if job.status in {"queued", "running"}
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.created_at)

    async def has_running_job(self) -> bool:
        return await self.get_active_job() is not None

    async def cancel_job(self, job_id: str) -> ChatJob | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        if job.status in {"done", "error", "cancelled"}:
            return job
        job.status = "cancelled"
        job.updated_at = time.time()
        if job.task is not None and not job.task.done():
            job.task.cancel()
        if not any(
            event.event == "error" and event.payload.get("error") == "cancelled"
            for event in job.events
        ):
            await self._append_event(
                job,
                "error",
                {"error": "cancelled", "job_id": job.job_id},
            )
        job.done.set()
        return job

    async def events_after(self, job: ChatJob, after: int) -> list[ChatJobEvent]:
        async with job.changed:
            return [event for event in job.events if event.seq > after]

    async def wait_for_events_after(
        self,
        job: ChatJob,
        after: int,
        *,
        timeout: float,
    ) -> list[ChatJobEvent]:
        async with job.changed:
            current = [event for event in job.events if event.seq > after]
            if current:
                return current
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return []
            return [event for event in job.events if event.seq > after]

    async def _run_job(self, job: ChatJob) -> None:
        job.status = "running"
        job.updated_at = time.time()
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
                registry=self._ctx.ai.attachment_registry,
                scope_key=webui_scope_key,
                strict=False,
            )
            if not rendered.delivery_text.strip():
                return
            outputs.append(rendered.delivery_text)
            job.outputs.append(rendered.delivery_text)
            await self._ctx.history_manager.add_private_message(
                user_id=_VIRTUAL_USER_ID,
                text_content=rendered.history_text,
                display_name="Bot",
                user_name="Bot",
                attachments=rendered.attachments,
            )
            await self._append_event(
                job,
                "message",
                {"content": rendered.delivery_text, "job_id": job.job_id},
            )

        async def _stream_event_callback(event: str, payload: dict[str, Any]) -> None:
            await self._append_event(
                job,
                event,
                {**_sanitize_stream_payload(event, payload), "job_id": job.job_id},
            )

        try:
            run_kwargs: dict[str, Any] = {
                "text": job.text,
                "send_output": _capture_private_message,
            }
            if "stream_event_callback" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["stream_event_callback"] = _stream_event_callback
            mode = await run_webui_chat(self._ctx, **run_kwargs)
            job.mode = mode
            job.status = "done"
            job.updated_at = time.time()
            done_payload = _build_chat_response_payload(mode, outputs)
            done_payload.update({"job_id": job.job_id, "status": job.status})
            await self._append_event(
                job,
                "done",
                done_payload,
            )
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.updated_at = time.time()
            if not any(
                event.event == "error" and event.payload.get("error") == "cancelled"
                for event in job.events
            ):
                await self._append_event(
                    job,
                    "error",
                    {"error": "cancelled", "job_id": job.job_id},
                )
        except Exception as exc:
            logger.exception("[RuntimeAPI] chat job failed: %s", exc)
            job.status = "error"
            job.error = str(exc)
            job.updated_at = time.time()
            await self._append_event(
                job,
                "error",
                {"error": str(exc), "job_id": job.job_id},
            )
        finally:
            job.done.set()

    async def _append_event(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> None:
        async with job.changed:
            normalized_event = str(payload.pop("_event", event) or event)
            item = ChatJobEvent(
                seq=job.next_seq, event=normalized_event, payload=payload
            )
            job.next_seq += 1
            job.updated_at = time.time()
            job.events.append(item)
            if len(job.events) > _CHAT_JOB_EVENT_BUFFER_LIMIT:
                job.events = job.events[-_CHAT_JOB_EVENT_BUFFER_LIMIT:]
            job.changed.notify_all()


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    text = str(value or "")
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _sanitize_stream_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event == "token_delta":
        return {"delta": str(payload.get("delta") or "")}
    if event == "tool_delta":
        return {
            "index": payload.get("index"),
            "tool_call_id": str(payload.get("id") or ""),
            "name": str(payload.get("name") or ""),
            "arguments_delta": _preview(payload.get("arguments_delta") or "", 300),
        }
    if event in {"tool_start", "agent_start"}:
        is_agent = bool(payload.get("is_agent")) or event == "agent_start"
        output_event = "agent_start" if is_agent else "tool_start"
        return {
            "_event": output_event,
            "tool_call_id": str(payload.get("tool_call_id") or ""),
            "name": str(payload.get("name") or ""),
            "api_name": str(payload.get("api_name") or ""),
            "arguments_preview": _preview(payload.get("arguments")),
            "is_agent": is_agent,
        }
    if event in {"tool_end", "agent_end"}:
        is_agent = bool(payload.get("is_agent")) or event == "agent_end"
        output_event = "agent_end" if is_agent else "tool_end"
        return {
            "_event": output_event,
            "tool_call_id": str(payload.get("tool_call_id") or ""),
            "name": str(payload.get("name") or ""),
            "api_name": str(payload.get("api_name") or ""),
            "ok": bool(payload.get("ok", True)),
            "result_preview": _preview(payload.get("result")),
            "is_agent": is_agent,
        }
    return {key: value for key, value in payload.items() if key != "arguments"}


async def _write_sse_event(response: web.StreamResponse, item: ChatJobEvent) -> None:
    await response.write(_sse_event(item.event, item.payload, item.seq))


def _parse_limit(request: web.Request, default: int = 50, maximum: int = 500) -> int:
    limit_raw = str(request.query.get("limit", str(default)) or str(default)).strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = default
    return max(1, min(limit, maximum))


def _parse_before(request: web.Request) -> int | None:
    raw = request.query.get("before")
    if raw is None:
        return None
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return max(0, int(text))
    except ValueError:
        return None


def _parse_after(request: web.Request) -> int:
    raw = request.query.get("after")
    if raw is None:
        raw = request.headers.get("Last-Event-ID")
    try:
        return max(0, int(str(raw or "0").strip()))
    except ValueError:
        return 0


def _history_record_to_item(item: dict[str, Any]) -> dict[str, Any] | None:
    content = str(item.get("message", "")).strip()
    if not content:
        return None
    display_name = str(item.get("display_name", "")).strip().lower()
    role = "bot" if display_name == "bot" else "user"
    return {
        "role": role,
        "content": content,
        "timestamp": str(item.get("timestamp", "") or "").strip(),
    }


async def run_webui_chat(
    ctx: RuntimeAPIContext,
    *,
    text: str,
    send_output: Callable[[int, str], Awaitable[None]],
    stream_event_callback: Callable[[str, dict[str, Any]], Awaitable[None]]
    | None = None,
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
                "stream_event_callback": stream_event_callback,
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

    limit = _parse_limit(request, default=50, maximum=500)
    before = _parse_before(request)

    page_getter = getattr(ctx.history_manager, "get_private_page", None)
    recent_getter = getattr(ctx.history_manager, "get_recent_private", None)
    if not callable(page_getter) and not callable(recent_getter):
        return _json_error("History manager not ready", status=503)

    if callable(page_getter):
        records, has_more, next_before, total = page_getter(
            _VIRTUAL_USER_ID,
            limit=limit,
            before=before,
        )
    elif callable(recent_getter):
        records = recent_getter(_VIRTUAL_USER_ID, limit)
        has_more = False
        next_before = None
        total = len(records)
    else:
        return _json_error("History manager not ready", status=503)
    items: list[dict[str, Any]] = []
    for record in records:
        if isinstance(record, dict):
            mapped = _history_record_to_item(record)
            if mapped is not None:
                items.append(mapped)

    return web.json_response(
        {
            "virtual_user_id": _VIRTUAL_USER_ID,
            "permission": "superadmin",
            "count": len(items),
            "items": items,
            "limit": limit,
            "before": before,
            "has_more": has_more,
            "next_before": next_before,
            "total": total,
        }
    )


async def chat_history_clear_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    """Clear WebUI virtual private chat history only."""

    _ = request
    if await job_manager.has_running_job():
        return _json_error("Chat job is still running", status=409)
    clearer = getattr(ctx.history_manager, "clear_private_history", None)
    if not callable(clearer):
        return _json_error("History manager not ready", status=503)
    cleared = await clearer(_VIRTUAL_USER_ID)
    return web.json_response(
        {
            "success": True,
            "virtual_user_id": _VIRTUAL_USER_ID,
            "cleared": int(cleared or 0),
        }
    )


async def chat_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
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
    if not stream:
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
    job = await job_manager.create_job(text)
    after = 0
    try:
        while True:
            if request.transport is None or request.transport.is_closing():
                break
            events = await job_manager.wait_for_events_after(
                job,
                after,
                timeout=_CHAT_SSE_KEEPALIVE_SECONDS,
            )
            if not events:
                await response.write(b": keep-alive\n\n")
                if job.done.is_set():
                    break
                continue
            for item in events:
                await _write_sse_event(response, item)
                after = item.seq
            if job.done.is_set() and after >= job.next_seq - 1:
                break
    except asyncio.CancelledError:
        raise
    except (ConnectionResetError, RuntimeError):
        pass
    except Exception as exc:
        logger.exception("[RuntimeAPI] chat stream failed: %s", exc)
        with suppress(Exception):
            await response.write(_sse_event("error", {"error": str(exc)}))
    finally:
        with suppress(Exception):
            await response.write_eof()

    return response


async def chat_job_create_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = ctx
    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)
    text = str(body.get("message", "") or "").strip()
    if not text:
        return _json_error("message is required", status=400)
    job = await job_manager.create_job(text)
    return web.json_response(job.snapshot(), status=202)


async def chat_job_active_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = ctx, request
    job = await job_manager.get_active_job()
    return web.json_response({"job": job.snapshot() if job is not None else None})


async def chat_job_detail_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = ctx
    job_id = str(request.match_info.get("job_id", "") or "").strip()
    job = await job_manager.get_job(job_id)
    if job is None:
        return _json_error("Job not found", status=404)
    return web.json_response(job.snapshot())


async def chat_job_cancel_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = ctx, request
    job_id = str(request.match_info.get("job_id", "") or "").strip()
    job = await job_manager.cancel_job(job_id)
    if job is None:
        return _json_error("Job not found", status=404)
    return web.json_response(job.snapshot())


async def chat_job_events_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> web.StreamResponse:
    _ = ctx
    job_id = str(request.match_info.get("job_id", "") or "").strip()
    job = await job_manager.get_job(job_id)
    if job is None:
        return _json_error("Job not found", status=404)
    after = _parse_after(request)

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
    try:
        while True:
            if request.transport is None or request.transport.is_closing():
                break
            events = await job_manager.wait_for_events_after(
                job,
                after,
                timeout=_CHAT_SSE_KEEPALIVE_SECONDS,
            )
            if not events:
                await response.write(b": keep-alive\n\n")
                if job.done.is_set():
                    break
                continue
            for item in events:
                await _write_sse_event(response, item)
                after = item.seq
            if job.done.is_set() and after >= job.next_seq - 1:
                break
    except asyncio.CancelledError:
        raise
    except (ConnectionResetError, RuntimeError):
        pass
    finally:
        with suppress(Exception):
            await response.write_eof()
    return response
