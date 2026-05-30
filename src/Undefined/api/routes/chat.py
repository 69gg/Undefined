"""Chat route handlers extracted from the Runtime API application."""

from __future__ import annotations

import asyncio
import inspect
import json
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
_CHAT_STAGE_REFRESH_SECONDS = 1.0
_CHAT_JOB_EVENT_BUFFER_LIMIT = 1000
_PREVIEW_LIMIT = 800
_WEBCHAT_SEND_MESSAGE_TOOLS = frozenset(
    {
        "messages.send_message",
        "send_message",
        "messages.send_private_message",
        "send_private_message",
    }
)
_WEBCHAT_LIFECYCLE_EVENTS = frozenset(
    {"tool_start", "tool_end", "agent_start", "agent_end"}
)
_WEBCHAT_HISTORY_EVENTS = _WEBCHAT_LIFECYCLE_EVENTS | frozenset({"message"})
_WEBCHAT_STAGE_EVENTS = frozenset({"stage"})


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
    finished_at: float | None = None
    duration_ms: int | None = None
    current_stage: str = "queued"
    current_stage_detail: str = ""
    current_stage_started_at: float = 0.0
    outputs: list[str] = field(default_factory=list)
    history_outputs: list[str] = field(default_factory=list)
    history_attachments: list[dict[str, str]] = field(default_factory=list)
    webchat_events: list[ChatJobEvent] = field(default_factory=list)
    events: list[ChatJobEvent] = field(default_factory=list)
    next_seq: int = 1
    task: asyncio.Task[None] | None = None
    error: str = ""
    history_finalized: bool = False
    cancel_finalizer_scheduled: bool = False
    history_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    tool_started_at: dict[str, float] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        elapsed_ms = _job_elapsed_ms(self, now)
        stage_elapsed_ms = _stage_elapsed_ms(self, now)
        return {
            "job_id": self.job_id,
            "status": self.status,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "elapsed_ms": elapsed_ms,
            "duration_ms": self.duration_ms,
            "current_stage": self.current_stage,
            "current_stage_detail": self.current_stage_detail or None,
            "current_stage_started_at": self.current_stage_started_at or None,
            "current_stage_elapsed_ms": stage_elapsed_ms,
            "last_seq": self.next_seq - 1,
            "error": self.error or None,
            "reply": "\n\n".join(self.outputs).strip(),
            "messages": list(self.outputs),
            "history_finalized": self.history_finalized,
        }

    def current_stage_event(self) -> ChatJobEvent | None:
        if self.done.is_set() or not self.current_stage:
            return None
        now = time.time()
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "stage": self.current_stage,
            "elapsed_ms": _job_elapsed_ms(self, now),
        }
        if self.current_stage_started_at > 0:
            payload["started_at"] = self.current_stage_started_at
            payload["stage_elapsed_ms"] = _stage_elapsed_ms(self, now)
        if self.current_stage_detail:
            payload["detail"] = self.current_stage_detail
        return ChatJobEvent(seq=self.next_seq - 1, event="stage", payload=payload)


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
        await self._append_stage(job, "received")
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
                if self._job_blocks_history_mutation(job)
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.created_at)

    async def has_running_job(self) -> bool:
        async with self._lock:
            return any(
                self._job_blocks_history_mutation(job) for job in self._jobs.values()
            )

    def _job_blocks_history_mutation(self, job: ChatJob) -> bool:
        if job.status in {"queued", "running"}:
            return True
        return not job.done.is_set() or not job.history_finalized

    async def clear_history_when_idle(self) -> int | None:
        async with self._lock:
            if any(
                self._job_blocks_history_mutation(job) for job in self._jobs.values()
            ):
                return None
            clearer = getattr(self._ctx.history_manager, "clear_private_history", None)
            if not callable(clearer):
                raise RuntimeError("History manager not ready")
            return int(await clearer(_VIRTUAL_USER_ID) or 0)

    async def cancel_job(self, job_id: str) -> ChatJob | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        if job.status in {"done", "error", "cancelled"}:
            return job
        job.status = "cancelled"
        self._mark_job_finished(job)
        if job.task is not None and not job.task.done():
            job.task.cancel()
            self._schedule_cancel_finalizer(job)
        if not any(
            event.event == "error" and event.payload.get("error") == "cancelled"
            for event in job.events
        ):
            await self._append_event(
                job,
                "error",
                {
                    "error": "cancelled",
                    "job_id": job.job_id,
                    "duration_ms": job.duration_ms,
                },
            )
        if job.task is None or job.task.done():
            job.history_finalized = True
            job.done.set()
        return job

    def _schedule_cancel_finalizer(self, job: ChatJob) -> None:
        if job.cancel_finalizer_scheduled:
            return
        if job.task is None:
            return
        job.cancel_finalizer_scheduled = True
        loop = asyncio.get_running_loop()

        def _on_done(_task: asyncio.Task[None]) -> None:
            loop.create_task(
                self._complete_cancelled_job(job),
                name=f"webchat-cancel-finalize:{job.job_id}",
            )

        job.task.add_done_callback(_on_done)

    async def _complete_cancelled_job(self, job: ChatJob) -> None:
        try:
            await self._finalize_job_history(job)
        except Exception as exc:
            logger.exception(
                "[RuntimeAPI] cancelled chat job history finalize failed: %s", exc
            )
            job.history_finalized = True
        finally:
            job.done.set()

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
            await self._append_stage(job, "sending_message")
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
            job.history_outputs.append(rendered.history_text)
            job.history_attachments.extend(rendered.attachments)
            now = time.time()
            await self._append_event(
                job,
                "message",
                {
                    "content": rendered.delivery_text,
                    "job_id": job.job_id,
                    "elapsed_ms": _job_elapsed_ms(job, now),
                },
            )

        async def _webchat_event_callback(event: str, payload: dict[str, Any]) -> None:
            if event in _WEBCHAT_STAGE_EVENTS:
                await self._append_stage(
                    job,
                    str(payload.get("stage") or payload.get("key") or ""),
                    detail=payload.get("detail"),
                )
                return
            if event not in {"tool_start", "tool_end", "agent_start", "agent_end"}:
                return
            event_payload = _sanitize_webchat_event_payload(event, payload)
            event_time = time.time()
            output_event = str(event_payload.get("_event", event) or event)
            tool_key = _webchat_tool_event_key(event_payload)
            if output_event in {"tool_start", "agent_start"}:
                job.tool_started_at[tool_key] = event_time
                event_payload["started_at"] = event_time
            elif output_event in {"tool_end", "agent_end"}:
                started_at = job.tool_started_at.pop(tool_key, None)
                if started_at is not None:
                    event_payload["duration_ms"] = max(
                        0, int((event_time - started_at) * 1000)
                    )
            event_payload["elapsed_ms"] = _job_elapsed_ms(job, event_time)
            event_payload["job_id"] = job.job_id
            await self._append_event(job, event, event_payload)

        try:
            run_kwargs: dict[str, Any] = {
                "text": job.text,
                "send_output": _capture_private_message,
            }
            if "webchat_event_callback" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["webchat_event_callback"] = _webchat_event_callback
            await self._append_stage(job, "processing")
            mode = await run_webui_chat(self._ctx, **run_kwargs)
            job.mode = mode
            job.status = "done"
            self._mark_job_finished(job)
            done_payload = _build_chat_response_payload(mode, outputs)
            done_payload.update(
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "duration_ms": job.duration_ms,
                }
            )
            await self._append_stage(job, "done")
            await self._append_event(
                job,
                "done",
                done_payload,
            )
        except asyncio.CancelledError:
            job.status = "cancelled"
            self._mark_job_finished(job)
            if not any(
                event.event == "error" and event.payload.get("error") == "cancelled"
                for event in job.events
            ):
                await self._append_event(
                    job,
                    "error",
                    {
                        "error": "cancelled",
                        "job_id": job.job_id,
                        "duration_ms": job.duration_ms,
                    },
                )
        except Exception as exc:
            logger.exception("[RuntimeAPI] chat job failed: %s", exc)
            job.status = "error"
            job.error = str(exc)
            self._mark_job_finished(job)
            await self._append_event(
                job,
                "error",
                {
                    "error": str(exc),
                    "job_id": job.job_id,
                    "duration_ms": job.duration_ms,
                },
            )
        finally:
            try:
                await self._finalize_job_history(job)
            except Exception as exc:
                logger.exception(
                    "[RuntimeAPI] chat job history finalize failed: %s", exc
                )
                job.history_finalized = True
            job.done.set()

    async def _append_event(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> ChatJobEvent:
        async with job.changed:
            payload_copy = dict(payload)
            normalized_event = str(payload_copy.pop("_event", event) or event)
            item = ChatJobEvent(
                seq=job.next_seq, event=normalized_event, payload=payload_copy
            )
            job.next_seq += 1
            job.updated_at = time.time()
            job.events.append(item)
            if len(job.events) > _CHAT_JOB_EVENT_BUFFER_LIMIT:
                job.events = job.events[-_CHAT_JOB_EVENT_BUFFER_LIMIT:]
            if item.event in _WEBCHAT_HISTORY_EVENTS:
                job.webchat_events.append(item)
                if len(job.webchat_events) > _CHAT_JOB_EVENT_BUFFER_LIMIT:
                    job.webchat_events = job.webchat_events[
                        -_CHAT_JOB_EVENT_BUFFER_LIMIT:
                    ]
            job.changed.notify_all()
            return item

    async def _append_stage(
        self,
        job: ChatJob,
        stage: str,
        *,
        detail: Any | None = None,
    ) -> ChatJobEvent | None:
        stage_key = str(stage or "").strip()
        if not stage_key:
            return None
        now = time.time()
        payload: dict[str, Any] = {
            "job_id": job.job_id,
            "stage": stage_key,
            "started_at": now,
            "elapsed_ms": _job_elapsed_ms(job, now),
        }
        detail_text = _preview(detail, 120)
        job.current_stage = stage_key
        job.current_stage_detail = detail_text
        job.current_stage_started_at = now
        if detail_text:
            payload["detail"] = detail_text
        return await self._append_event(job, "stage", payload)

    def _mark_job_finished(self, job: ChatJob) -> None:
        now = time.time()
        job.finished_at = now
        job.duration_ms = _job_elapsed_ms(job, now)
        job.updated_at = now

    async def _finalize_job_history(self, job: ChatJob) -> None:
        async with job.history_lock:
            if job.history_finalized:
                return
            text_content = "\n\n".join(job.history_outputs).strip()
            webchat = _build_webchat_history_payload(job)
            if text_content or webchat["events"]:
                await self._ctx.history_manager.add_private_message(
                    user_id=_VIRTUAL_USER_ID,
                    text_content=text_content,
                    display_name="Bot",
                    user_name="Bot",
                    attachments=job.history_attachments or None,
                    webchat=webchat,
                )
                flusher = getattr(
                    self._ctx.history_manager, "flush_pending_saves", None
                )
                if callable(flusher):
                    maybe_awaitable = flusher()
                    if inspect.isawaitable(maybe_awaitable):
                        await maybe_awaitable
            job.history_finalized = True


def _job_elapsed_ms(job: ChatJob, now: float | None = None) -> int:
    measured_at = time.time() if now is None else now
    return max(0, int((measured_at - job.created_at) * 1000))


def _stage_elapsed_ms(job: ChatJob, now: float | None = None) -> int:
    if job.current_stage_started_at <= 0:
        return 0
    measured_at = time.time() if now is None else now
    return max(0, int((measured_at - job.current_stage_started_at) * 1000))


def _webchat_tool_event_key(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("webchat_call_id") or "").strip()
        or str(payload.get("tool_call_id") or "").strip()
        or str(payload.get("name") or "").strip()
        or str(payload.get("api_name") or "").strip()
        or "tool"
    )


def _webchat_payload_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    call_id = (
        str(payload.get("webchat_call_id") or "").strip()
        or str(payload.get("tool_call_id") or "").strip()
        or str(payload.get("name") or "").strip()
        or "tool"
    )
    parent_call_id = str(payload.get("parent_webchat_call_id") or "").strip()
    try:
        depth = max(0, int(payload.get("depth", 0) or 0))
    except (TypeError, ValueError):
        depth = 0
    raw_path = payload.get("agent_path")
    agent_path = (
        [str(item) for item in raw_path if str(item).strip()]
        if isinstance(raw_path, list)
        else []
    )
    return {
        "webchat_call_id": call_id,
        "parent_webchat_call_id": parent_call_id,
        "depth": depth,
        "agent_path": agent_path,
    }


def _legacy_webchat_tool_event_key(payload: dict[str, Any]) -> str:
    return (
        str(payload.get("tool_call_id") or "").strip()
        or str(payload.get("name") or "").strip()
        or str(payload.get("api_name") or "").strip()
        or "tool"
    )


def _preview(value: Any, limit: int = _PREVIEW_LIMIT) -> str:
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value or "")
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _webchat_tool_ui_hint(
    event: str,
    *,
    name: str,
    api_name: str,
    arguments: Any | None = None,
    result: Any | None = None,
    is_agent: bool = False,
) -> str | None:
    if is_agent:
        return None
    tool_names = {name, api_name}
    if tool_names & _WEBCHAT_SEND_MESSAGE_TOOLS:
        if tool_names & {"messages.send_private_message", "send_private_message"}:
            return "webchat_private_send"
        if not isinstance(arguments, dict):
            return None
        target_type = str(arguments.get("target_type") or "").strip().lower()
        if target_type in {"", "private"}:
            return "webchat_private_send"
        return None
    if "end" in tool_names and event in {"tool_end", "agent_end"}:
        result_text = str(result or "").strip()
        if result_text == "对话已结束":
            return "webchat_end"
    return None


def _sanitize_webchat_event_payload(
    event: str, payload: dict[str, Any]
) -> dict[str, Any]:
    if event in {"tool_start", "agent_start"}:
        is_agent = bool(payload.get("is_agent")) or event == "agent_start"
        output_event = "agent_start" if is_agent else "tool_start"
        name = str(payload.get("name") or "")
        api_name = str(payload.get("api_name") or "")
        arguments = payload.get("arguments")
        ui_hint = _webchat_tool_ui_hint(
            output_event,
            name=name,
            api_name=api_name,
            arguments=arguments,
            is_agent=is_agent,
        )
        return {
            "_event": output_event,
            "tool_call_id": str(payload.get("tool_call_id") or ""),
            "name": name,
            "api_name": api_name,
            "status": "running",
            "arguments_preview": ""
            if ui_hint == "webchat_private_send"
            else _preview(arguments),
            "is_agent": is_agent,
            **_webchat_payload_lineage(payload),
            **({"ui_hint": ui_hint} if ui_hint else {}),
        }
    if event in {"tool_end", "agent_end"}:
        is_agent = bool(payload.get("is_agent")) or event == "agent_end"
        output_event = "agent_end" if is_agent else "tool_end"
        name = str(payload.get("name") or "")
        api_name = str(payload.get("api_name") or "")
        result = payload.get("result")
        ui_hint = _webchat_tool_ui_hint(
            output_event,
            name=name,
            api_name=api_name,
            result=result,
            is_agent=is_agent,
        )
        return {
            "_event": output_event,
            "tool_call_id": str(payload.get("tool_call_id") or ""),
            "name": name,
            "api_name": api_name,
            "ok": bool(payload.get("ok", True)),
            "status": "error" if payload.get("ok") is False else "done",
            "result_preview": ""
            if ui_hint in {"webchat_private_send", "webchat_end"}
            else _preview(result),
            "is_agent": is_agent,
            **_webchat_payload_lineage(payload),
            **({"ui_hint": ui_hint} if ui_hint else {}),
        }
    return {key: value for key, value in payload.items() if key != "arguments"}


def _build_webchat_history_payload(job: ChatJob) -> dict[str, Any]:
    events = _finalize_webchat_history_events(job)
    return {
        "display_only": True,
        "job_id": job.job_id,
        "mode": job.mode,
        "status": job.status,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "duration_ms": job.duration_ms,
        "events": events,
        "calls": _build_webchat_call_tree(events),
        "timeline": _build_webchat_timeline(events),
    }


def _finalize_webchat_history_events(job: ChatJob) -> list[dict[str, Any]]:
    events = [
        {
            "seq": item.seq,
            "event": item.event,
            "payload": dict(item.payload),
        }
        for item in job.webchat_events
    ]
    if job.status == "done":
        return events
    started: dict[str, dict[str, Any]] = {}
    closed: set[str] = set()
    for item in events:
        event = str(item.get("event") or "")
        if event not in _WEBCHAT_LIFECYCLE_EVENTS:
            continue
        call_id = _webchat_event_call_id(item)
        if not call_id:
            continue
        payload = item.get("payload")
        payload_dict = payload if isinstance(payload, dict) else {}
        if event in {"tool_start", "agent_start"}:
            started[call_id] = dict(payload_dict)
            continue
        if event in {"tool_end", "agent_end"}:
            closed.add(call_id)
    unfinished = [call_id for call_id in started if call_id not in closed]
    if not unfinished:
        return events
    reason = "cancelled" if job.status == "cancelled" else "interrupted"
    finished_at = job.finished_at or time.time()
    max_seq = 0
    for item in events:
        seq_raw = item.get("seq", 0)
        if not isinstance(seq_raw, str | bytes | int | float):
            continue
        try:
            max_seq = max(max_seq, int(seq_raw))
        except (TypeError, ValueError):
            continue
    next_seq = max_seq + 1
    for call_id in unfinished:
        start_payload = started[call_id]
        started_at = start_payload.get("started_at")
        duration_ms = None
        if isinstance(started_at, int | float):
            duration_ms = max(0, int((finished_at - float(started_at)) * 1000))
        events.append(
            {
                "seq": next_seq,
                "event": "agent_end" if start_payload.get("is_agent") else "tool_end",
                "payload": {
                    "tool_call_id": str(start_payload.get("tool_call_id") or ""),
                    "name": str(start_payload.get("name") or ""),
                    "api_name": str(start_payload.get("api_name") or ""),
                    "ok": False,
                    "status": "cancelled" if reason == "cancelled" else "error",
                    "result_preview": reason,
                    "is_agent": bool(start_payload.get("is_agent")),
                    "webchat_call_id": call_id,
                    "parent_webchat_call_id": str(
                        start_payload.get("parent_webchat_call_id") or ""
                    ),
                    "depth": start_payload.get("depth", 0),
                    "agent_path": start_payload.get("agent_path")
                    if isinstance(start_payload.get("agent_path"), list)
                    else [],
                    "duration_ms": duration_ms,
                    "elapsed_ms": _job_elapsed_ms(job, finished_at),
                    "job_id": job.job_id,
                },
            }
        )
        next_seq += 1
    return events


def _call_preview_node(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "webchat_call_id": str(payload.get("webchat_call_id") or "").strip(),
        "parent_webchat_call_id": str(
            payload.get("parent_webchat_call_id") or ""
        ).strip(),
        "tool_call_id": str(payload.get("tool_call_id") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "api_name": str(payload.get("api_name") or "").strip(),
        "is_agent": bool(payload.get("is_agent")),
        "status": str(payload.get("status") or "running"),
        "ok": None,
        "arguments_preview": str(payload.get("arguments_preview") or ""),
        "result_preview": "",
        "ui_hint": str(payload.get("ui_hint") or "").strip(),
        "duration_ms": payload.get("duration_ms"),
        "elapsed_ms": payload.get("elapsed_ms"),
        "started_at": payload.get("started_at"),
        "depth": payload.get("depth", 0),
        "agent_path": payload.get("agent_path")
        if isinstance(payload.get("agent_path"), list)
        else [],
        "children": [],
    }


def _webchat_event_call_id(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    call_id = str(payload.get("webchat_call_id") or "").strip()
    return call_id or _legacy_webchat_tool_event_key(payload)


def _build_webchat_call_graph(
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in events:
        event = str(item.get("event") or "")
        if event not in _WEBCHAT_LIFECYCLE_EVENTS:
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        call_id = _webchat_event_call_id(item)
        if not call_id:
            continue
        node = nodes.get(call_id)
        if node is None:
            node = _call_preview_node({**payload, "webchat_call_id": call_id})
            nodes[call_id] = node
            order.append(call_id)
        if event in {"tool_start", "agent_start"}:
            node.update(_call_preview_node({**payload, "webchat_call_id": call_id}))
            node["status"] = "running"
            continue
        if event in {"tool_end", "agent_end"}:
            node.update(
                {
                    "status": str(
                        payload.get("status")
                        or ("error" if payload.get("ok") is False else "done")
                    ),
                    "ok": bool(payload.get("ok", True)),
                    "result_preview": str(payload.get("result_preview") or ""),
                    "duration_ms": payload.get("duration_ms"),
                    "elapsed_ms": payload.get("elapsed_ms"),
                    "ui_hint": str(payload.get("ui_hint") or node.get("ui_hint") or ""),
                    "is_agent": bool(payload.get("is_agent") or node.get("is_agent")),
                }
            )

    for call_id in order:
        nodes[call_id]["children"] = []
    roots: list[dict[str, Any]] = []
    for call_id in order:
        node = nodes[call_id]
        parent_id = str(node.get("parent_webchat_call_id") or "").strip()
        parent = nodes.get(parent_id)
        if parent is not None and parent is not node:
            parent.setdefault("children", []).append(node)
        else:
            roots.append(node)
    return nodes, order, roots


def _build_webchat_call_tree(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _nodes, _order, roots = _build_webchat_call_graph(events)
    return roots


def _build_webchat_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes, _order, _roots = _build_webchat_call_graph(events)
    emitted_calls: set[str] = set()
    timeline: list[dict[str, Any]] = []
    for item in events:
        event = str(item.get("event") or "")
        seq_raw = item.get("seq", 0)
        try:
            seq = max(0, int(seq_raw))
        except (TypeError, ValueError):
            seq = 0
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if event == "message":
            content = str(payload.get("content") or payload.get("message") or "")
            if content:
                timeline.append(
                    {
                        "type": "message",
                        "seq": seq,
                        "content": content,
                        "elapsed_ms": payload.get("elapsed_ms"),
                    }
                )
            continue
        if event not in _WEBCHAT_LIFECYCLE_EVENTS:
            continue
        call_id = _webchat_event_call_id(item)
        if not call_id or call_id in emitted_calls:
            continue
        node = nodes.get(call_id)
        if node is None:
            continue
        parent_id = str(node.get("parent_webchat_call_id") or "").strip()
        if parent_id and parent_id in nodes:
            continue
        emitted_calls.add(call_id)
        timeline.append({"type": "call", "seq": seq, "call": node})
    return timeline


def _webchat_history_events(webchat: Any) -> list[dict[str, Any]]:
    if not isinstance(webchat, dict):
        return []
    raw_events = webchat.get("events")
    if not isinstance(raw_events, list):
        return []
    events: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", "") or "").strip()
        if event not in _WEBCHAT_HISTORY_EVENTS:
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        seq_raw = item.get("seq", 0)
        try:
            seq = max(0, int(seq_raw))
        except (TypeError, ValueError):
            seq = 0
        events.append({"seq": seq, "event": event, "payload": dict(payload)})
    return events


def _webchat_history_calls(webchat: Any) -> list[dict[str, Any]]:
    if not isinstance(webchat, dict):
        return []
    raw_calls = webchat.get("calls")
    if isinstance(raw_calls, list):
        return [item for item in raw_calls if isinstance(item, dict)]
    return _build_webchat_call_tree(_webchat_history_events(webchat))


def _webchat_history_timeline(webchat: Any) -> list[dict[str, Any]]:
    if not isinstance(webchat, dict):
        return []
    raw_timeline = webchat.get("timeline")
    if isinstance(raw_timeline, list):
        return [item for item in raw_timeline if isinstance(item, dict)]
    return _build_webchat_timeline(_webchat_history_events(webchat))


def _is_webchat_display_only_record(item: dict[str, Any]) -> bool:
    if str(item.get("message", "") or "").strip():
        return False
    webchat = item.get("webchat")
    if not isinstance(webchat, dict):
        return False
    return bool(webchat.get("display_only")) and bool(_webchat_history_events(webchat))


def _filter_webchat_display_only_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [item for item in records if not _is_webchat_display_only_record(item)]


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
    webchat = item.get("webchat")
    webchat_events = _webchat_history_events(webchat)
    if not content and not webchat_events:
        return None
    display_name = str(item.get("display_name", "")).strip().lower()
    role = "bot" if display_name == "bot" else "user"
    mapped: dict[str, Any] = {
        "role": role,
        "content": content,
        "timestamp": str(item.get("timestamp", "") or "").strip(),
    }
    if isinstance(webchat, dict) and webchat_events:
        webchat_calls = _webchat_history_calls(webchat)
        webchat_timeline = _webchat_history_timeline(webchat)
        mapped["webchat"] = {
            "display_only": bool(webchat.get("display_only")),
            "job_id": str(webchat.get("job_id", "") or "").strip(),
            "mode": str(webchat.get("mode", "") or "").strip(),
            "status": str(webchat.get("status", "") or "").strip(),
            "created_at": webchat.get("created_at"),
            "finished_at": webchat.get("finished_at"),
            "duration_ms": webchat.get("duration_ms"),
            "events": webchat_events,
            "calls": webchat_calls,
            "timeline": webchat_timeline,
        }
    return mapped


async def run_webui_chat(
    ctx: RuntimeAPIContext,
    *,
    text: str,
    send_output: Callable[[int, str], Awaitable[None]],
    webchat_event_callback: Callable[[str, dict[str, Any]], Awaitable[None]]
    | None = None,
) -> str:
    """Execute a single WebUI chat turn (command dispatch or AI ask)."""

    async def emit_stage(stage: str, detail: Any | None = None) -> None:
        if webchat_event_callback is None:
            return
        await webchat_event_callback(
            "stage",
            {"stage": stage, **({"detail": detail} if detail is not None else {})},
        )

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
    await emit_stage("recording_history")
    await ctx.history_manager.add_private_message(
        user_id=_VIRTUAL_USER_ID,
        text_content=normalized_text,
        display_name=_VIRTUAL_USER_NAME,
        user_name=_VIRTUAL_USER_NAME,
        attachments=registered_input.attachments,
    )

    command = ctx.command_dispatcher.parse_command(normalized_text)
    if command:
        await emit_stage("running_command")
        await ctx.command_dispatcher.dispatch_private(
            user_id=_VIRTUAL_USER_ID,
            sender_id=permission_sender_id,
            command=command,
            send_private_callback=send_output,
            is_webui_session=True,
        )
        await emit_stage("command_done")
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
        recent_messages = await get_recent_messages_prefer_local(
            chat_id=chat_id,
            msg_type=msg_type,
            start=start,
            end=end,
            onebot_client=ctx.onebot,
            history_manager=ctx.history_manager,
            bot_qq=cfg.bot_qq,
            attachment_registry=getattr(ctx.ai, "attachment_registry", None),
        )
        return _filter_webchat_display_only_records(recent_messages)

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

        await emit_stage("asking_ai")
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
                "webchat_event_callback": webchat_event_callback,
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
    if not hasattr(ctx.history_manager, "clear_private_history"):
        return _json_error("History manager not ready", status=503)
    try:
        cleared = await job_manager.clear_history_when_idle()
    except RuntimeError:
        return _json_error("History manager not ready", status=503)
    if cleared is None:
        return _json_error("Chat job is still running", status=409)
    return web.json_response(
        {
            "success": True,
            "virtual_user_id": _VIRTUAL_USER_ID,
            "cleared": cleared,
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
                timeout=min(_CHAT_STAGE_REFRESH_SECONDS, _CHAT_SSE_KEEPALIVE_SECONDS),
            )
            if not events:
                stage_event = job.current_stage_event()
                if stage_event is not None:
                    await _write_sse_event(response, stage_event)
                    after = max(after, stage_event.seq)
                else:
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
                timeout=min(_CHAT_STAGE_REFRESH_SECONDS, _CHAT_SSE_KEEPALIVE_SECONDS),
            )
            if not events:
                stage_event = job.current_stage_event()
                if stage_event is not None:
                    await _write_sse_event(response, stage_event)
                    after = max(after, stage_event.seq)
                else:
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
