"""Chat route handlers extracted from the Runtime API application."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import mimetypes
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Awaitable, Callable
from urllib.parse import unquote
from uuid import uuid4

import aiofiles
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
from Undefined.api.webchat_store import (
    DEFAULT_WEBCHAT_CONVERSATION_ID,
    WebChatConversationStore,
    format_webchat_message_xml,
    generate_webchat_title,
    webchat_title_basis_hash,
)
from Undefined.attachments import (
    attachment_refs_to_xml,
    build_attachment_scope,
    register_message_attachments,
)
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.services.queue_manager import QUEUE_LANE_SUPERADMIN
from Undefined.utils.common import message_to_segments
from Undefined.utils import io as async_io
from Undefined.utils.paths import WEBCHAT_DIR, ensure_dir
from Undefined.utils.recent_messages import get_recent_messages_prefer_local

logger = logging.getLogger(__name__)

_VIRTUAL_USER_NAME = "system"
_DEFAULT_CONVERSATION_ID = DEFAULT_WEBCHAT_CONVERSATION_ID
_CHAT_SSE_KEEPALIVE_SECONDS = 10.0
_CHAT_STAGE_REFRESH_SECONDS = 1.0
_CHAT_JOB_EVENT_BUFFER_LIMIT = 1000
SHUTDOWN_TASK_TIMEOUT = 5.0

# register_message_attachments 产出的可读占位（如 ``[图片 uid=pic_xxx name=foo]``）
_WEBCHAT_BRACKET_REF_PATTERN = re.compile(r"\[[^\]]*?\buid=(?P<uid>[^\s\]]+)[^\]]*?\]")
# 文本中所有 <attachment.../> / <pic.../> 引用
_WEBCHAT_ATTACHMENT_TAG_PATTERN = re.compile(
    r"<(?:attachment|pic)\s+[^>]*?\buid=[\"']?(?P<uid>[^\"'\s/>]+)[\"']?[^>]*?/?>",
    re.IGNORECASE,
)


async def _normalize_webchat_output(
    content: str,
    *,
    registry: Any,
    scope_key: str | None,
    resolve_image_url: Callable[[str], Awaitable[str | None]] | None,
    get_forward_messages: Callable[[str], Awaitable[list[dict[str, Any]]]] | None,
) -> tuple[str, list[dict[str, str]]]:
    """归一化 webchat 命令输出中的内联媒体，统一为 ``<attachment uid/>``。

    命令输出可能包含原始 ``[CQ:image,file=base64://...]`` / ``file://`` 图片。
    若原样写入历史，会把整段 base64 喂给后续 LLM（导致 token 爆炸），也让 API
    返回 base64。这里先把内联媒体注册为附件、转成 ``<attachment uid/>`` 占位，
    客户端再按 UID 经 ``/api/v1/chat/attachments/{uid}/preview`` 拉取渲染。

    Args:
        content: 命令输出原文。
        registry: 附件注册表。
        scope_key: 当前 webchat 会话作用域键。
        resolve_image_url: 将 ``file`` 字段解析为可下载 URL 的回调。
        get_forward_messages: 拉取合并转发子消息的回调。

    Returns:
        ``(归一化文本, 附件引用列表)``；附件为 :meth:`AttachmentRecord.prompt_ref` 字典。
    """
    if registry is None or not scope_key or not content.strip():
        return content, []
    segments = message_to_segments(content)
    registered = await register_message_attachments(
        registry=registry,
        segments=segments,
        scope_key=scope_key,
        resolve_image_url=resolve_image_url,
        get_forward_messages=get_forward_messages,
    )
    text = registered.normalized_text or content
    # ``[图片 uid=X name=Y]`` / ``[文件 uid=X]`` → ``<attachment uid="X"/>``
    text = _WEBCHAT_BRACKET_REF_PATTERN.sub(
        lambda match: f'<attachment uid="{match.group("uid")}"/>', text
    )
    # 收集文中所有附件引用（含技能预先注册、已是 <attachment>/<pic> 标签的）
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _WEBCHAT_ATTACHMENT_TAG_PATTERN.finditer(text):
        uid = str(match.group("uid") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        record = await registry.resolve_async(uid, scope_key)
        if record is not None:
            attachments.append(record.prompt_ref())
    return text, attachments


_PREVIEW_LIMIT = 800
_CHAT_ATTACHMENT_MAX_NAME_LENGTH = 128
_CHAT_ATTACHMENT_UPLOAD_FIELD = "file"
_CHAT_ATTACHMENT_CHUNK_SIZE = 1024 * 256
_CHAT_ATTACHMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,96}$")
_CHAT_ATTACHMENT_STORAGE_DIR = WEBCHAT_DIR / "attachments"
_CHAT_ATTACHMENT_BLOB_DIR = _CHAT_ATTACHMENT_STORAGE_DIR / "blobs"
_CHAT_ATTACHMENT_META_DIR = _CHAT_ATTACHMENT_STORAGE_DIR / "metadata"
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
_WEBCHAT_AGENT_STAGE_EVENTS = frozenset({"agent_stage"})
_WEBCHAT_ACTION_EVENTS = frozenset({"requires_action"})
_WEBCHAT_HISTORY_EVENTS = (
    _WEBCHAT_LIFECYCLE_EVENTS
    | _WEBCHAT_AGENT_STAGE_EVENTS
    | _WEBCHAT_ACTION_EVENTS
    | frozenset({"message"})
)
_WEBCHAT_STAGE_EVENTS = frozenset({"stage"})
_REDACTED_PREVIEW_VALUE = "[redacted]"
_SENSITIVE_KEY_EXACT = frozenset(
    {
        "apikey",
        "authorization",
        "authtoken",
        "bearertoken",
        "clientsecret",
        "cookie",
        "credentials",
        "idtoken",
        "password",
        "passwd",
        "privatekey",
        "refreshtoken",
        "secret",
        "secretkey",
        "sessioncookie",
        "sessionid",
        "sessiontoken",
        "setcookie",
        "token",
    }
)
_SENSITIVE_KEY_SUFFIXES = (
    "apikey",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "idtoken",
    "privatekey",
    "refreshtoken",
    "secretkey",
    "sessioncookie",
    "sessionid",
    "sessiontoken",
)
_SECRET_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(authorization)\s*[:=]\s*(bearer\s+)?([^\s,;]+)",
    ),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
        r"client[_-]?secret|password|passwd|secret|private[_-]?key|session[_-]?id|"
        r"session[_-]?token|cookie|set-cookie)\s*[:=]\s*(['\"]?)([^,\s;&\n'\"]+)",
    ),
    re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+/=-]{16,})"),
)


@dataclass
class ChatJobEvent:
    seq: int
    event: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class StructuredChatMessage:
    text: str
    attachments: list[dict[str, str]]
    references: list[dict[str, Any]]


class ChatAttachmentNotFoundError(LookupError):
    """Raised when a structured WebChat payload references a missing attachment."""


@dataclass
class ChatJob:
    job_id: str
    text: str
    created_at: float
    updated_at: float
    conversation_id: str = _DEFAULT_CONVERSATION_ID
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
    user_history_attachments: list[dict[str, str]] = field(default_factory=list)
    user_history_references: list[dict[str, Any]] = field(default_factory=list)
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
    tool_start_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_current_stage: dict[str, str] = field(default_factory=dict)
    agent_stage_started_at: dict[str, float] = field(default_factory=dict)
    agent_stage_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_history_pre_recorded: bool = False

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        elapsed_ms = _job_elapsed_ms(self, now)
        stage_elapsed_ms = _stage_elapsed_ms(self, now)
        return {
            "job_id": self.job_id,
            "conversation_id": self.conversation_id,
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
            "current_agent_stages": self.current_agent_stage_snapshots(now),
            "current_tool_calls": self.current_tool_call_snapshots(now),
            "history_finalized": self.history_finalized,
            "waiting_input": None,
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

    def current_agent_stage_events(self) -> list[ChatJobEvent]:
        if self.done.is_set():
            return []
        now = time.time()
        payloads = self.current_agent_stage_snapshots(now)
        return [
            ChatJobEvent(seq=self.next_seq - 1, event="agent_stage", payload=payload)
            for payload in payloads
        ]

    def current_agent_stage_snapshots(
        self, now: float | None = None
    ) -> list[dict[str, Any]]:
        if self.done.is_set():
            return []
        measured_at = time.time() if now is None else now
        payloads: list[dict[str, Any]] = []
        for call_id, stage in self.agent_current_stage.items():
            if not stage:
                continue
            payload = dict(self.agent_stage_payloads.get(call_id, {}))
            started_at = self.agent_stage_started_at.get(call_id, measured_at)
            payload.update(
                {
                    "job_id": self.job_id,
                    "webchat_call_id": call_id,
                    "stage": stage,
                    "transient": True,
                    "started_at": started_at,
                    "stage_elapsed_ms": max(0, int((measured_at - started_at) * 1000)),
                    "elapsed_ms": _job_elapsed_ms(self, measured_at),
                }
            )
            payloads.append(payload)
        return payloads

    def current_tool_call_snapshots(
        self, now: float | None = None
    ) -> list[dict[str, Any]]:
        if self.done.is_set():
            return []
        measured_at = time.time() if now is None else now
        payloads: list[dict[str, Any]] = []
        for call_id, started_at in self.tool_started_at.items():
            payload = dict(self.tool_start_payloads.get(call_id, {}))
            if not payload:
                continue
            payload.update(
                {
                    "job_id": self.job_id,
                    "webchat_call_id": call_id,
                    "status": "running",
                    "started_at": started_at,
                    "duration_ms": max(0, int((measured_at - started_at) * 1000)),
                    "elapsed_ms": _job_elapsed_ms(self, measured_at),
                }
            )
            if bool(payload.get("is_agent")):
                stage_payload = self.agent_stage_payloads.get(call_id, {})
                stage_started_at = self.agent_stage_started_at.get(call_id, measured_at)
                current_stage = self.agent_current_stage.get(call_id, "")
                if current_stage:
                    payload.update(
                        {
                            "current_stage": current_stage,
                            "current_stage_detail": str(
                                stage_payload.get("detail") or ""
                            ).strip(),
                            "current_stage_elapsed_ms": max(
                                0,
                                int((measured_at - stage_started_at) * 1000),
                            ),
                        }
                    )
            payloads.append(payload)
        return payloads


class ChatJobManager:
    def __init__(self, ctx: RuntimeAPIContext) -> None:
        self._ctx = ctx
        self._jobs: dict[str, ChatJob] = {}
        self._lock = asyncio.Lock()
        self._title_schedule_lock = asyncio.Lock()
        self.conversation_store = WebChatConversationStore()

    async def create_job(
        self,
        text: str,
        conversation_id: str | None = None,
        *,
        user_history_attachments: list[dict[str, str]] | None = None,
        user_history_references: list[dict[str, Any]] | None = None,
        pre_record_user_history: bool = False,
    ) -> ChatJob:
        await self.conversation_store.ensure_ready(self._ctx.history_manager)
        requested_conversation_id = str(conversation_id or "").strip()
        resolved_conversation_id = requested_conversation_id or _DEFAULT_CONVERSATION_ID
        conversation = await self.conversation_store.get_conversation(
            resolved_conversation_id
        )
        if conversation is None:
            if requested_conversation_id:
                raise KeyError(resolved_conversation_id)
            conversation = await self.conversation_store.ensure_default_conversation()
            resolved_conversation_id = str(conversation["id"])
        now = time.time()
        job = ChatJob(
            job_id=uuid4().hex,
            text=text,
            created_at=now,
            updated_at=now,
            conversation_id=resolved_conversation_id,
            user_history_attachments=list(user_history_attachments or []),
            user_history_references=list(user_history_references or []),
            user_history_pre_recorded=pre_record_user_history,
        )
        async with self._lock:
            if any(
                self._job_blocks_history_mutation(existing)
                for existing in self._jobs.values()
                if existing.conversation_id == resolved_conversation_id
            ):
                raise RuntimeError("Chat job is still running")
            self._jobs[job.job_id] = job
        if pre_record_user_history:
            await self.conversation_store.append_message(
                resolved_conversation_id,
                role="user",
                text_content=text,
                display_name=_VIRTUAL_USER_NAME,
                user_name=_VIRTUAL_USER_NAME,
                attachments=job.user_history_attachments or None,
                references=job.user_history_references or None,
            )
        logger.info(
            "[RuntimeAPI][WebChat] 创建 job: job_id=%s conversation_id=%s text_len=%s",
            job.job_id,
            job.conversation_id,
            len(text),
        )
        await self._append_event(
            job,
            "meta",
            {
                "job_id": job.job_id,
                "conversation_id": job.conversation_id,
                "virtual_user_id": _VIRTUAL_USER_ID,
                "permission": "superadmin",
            },
        )
        await self._append_stage(job, "received")
        job.task = asyncio.create_task(self._run_job(job), name=f"webchat:{job.job_id}")
        return job

    async def stop(self) -> None:
        async with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if self._job_blocks_history_mutation(job):
                await self.cancel_job(job.job_id)
        tasks: list[asyncio.Task[None]] = []
        for job in jobs:
            task = job.task
            if task is not None and not task.done():
                tasks.append(task)
        if tasks:
            task_wait = asyncio.gather(*tasks, return_exceptions=True)
            try:
                await asyncio.wait_for(
                    asyncio.shield(task_wait),
                    timeout=SHUTDOWN_TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[RuntimeAPI][WebChat] stop 等待 job task 超时，重新取消未完成任务: tasks=%s",
                    len(tasks),
                )
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await task_wait
        for job in jobs:
            if not job.done.is_set():
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(job.done.wait(), timeout=5.0)
        await self.conversation_store.stop()

    async def get_job(self, job_id: str) -> ChatJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def get_active_job(
        self, conversation_id: str | None = None
    ) -> ChatJob | None:
        candidates = await self.get_active_jobs(conversation_id)
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.created_at)

    async def get_active_jobs(
        self, conversation_id: str | None = None
    ) -> list[ChatJob]:
        resolved_conversation_id = str(conversation_id or "").strip()
        async with self._lock:
            candidates = [
                job
                for job in self._jobs.values()
                if self._job_blocks_history_mutation(job)
                and (
                    not resolved_conversation_id
                    or job.conversation_id == resolved_conversation_id
                )
            ]
        return sorted(candidates, key=lambda item: item.created_at)

    async def snapshot(self, job: ChatJob) -> dict[str, Any]:
        async with job.changed:
            return job.snapshot()

    async def has_running_job(self, conversation_id: str | None = None) -> bool:
        resolved_conversation_id = str(conversation_id or "").strip()
        async with self._lock:
            return any(
                self._job_blocks_history_mutation(job)
                and (
                    not resolved_conversation_id
                    or job.conversation_id == resolved_conversation_id
                )
                for job in self._jobs.values()
            )

    def _job_blocks_history_mutation(self, job: ChatJob) -> bool:
        if job.status in {"queued", "running"}:
            return True
        return not job.done.is_set() or not job.history_finalized

    async def clear_history_when_idle(
        self, conversation_id: str | None = None
    ) -> int | None:
        await self.conversation_store.ensure_ready(self._ctx.history_manager)
        resolved_conversation_id = (
            str(conversation_id or _DEFAULT_CONVERSATION_ID).strip()
            or _DEFAULT_CONVERSATION_ID
        )
        async with self._lock:
            if any(
                self._job_blocks_history_mutation(job)
                and job.conversation_id == resolved_conversation_id
                for job in self._jobs.values()
            ):
                logger.info(
                    "[RuntimeAPI][WebChat] 清空历史被拒绝，存在运行中 job: conversation_id=%s",
                    resolved_conversation_id,
                )
                return None
            return int(
                await self.conversation_store.clear_conversation(
                    resolved_conversation_id
                )
                or 0
            )

    async def cancel_job(self, job_id: str) -> ChatJob | None:
        job = await self.get_job(job_id)
        if job is None:
            return None
        if job.status in {"done", "error", "cancelled"}:
            return job
        logger.info(
            "[RuntimeAPI][WebChat] 取消 job: job_id=%s conversation_id=%s status=%s",
            job.job_id,
            job.conversation_id,
            job.status,
        )
        async with job.changed:
            job.status = "cancelled"
            self._mark_job_finished(job)
            job.changed.notify_all()
        if job.task is not None and not job.task.done():
            job.task.cancel()
            self._schedule_cancel_finalizer(job)
        await self._append_cancelled_event_once(job)
        if job.task is None or job.task.done():
            async with job.changed:
                job.history_finalized = True
                job.done.set()
                job.changed.notify_all()
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
            async with job.changed:
                job.done.set()
                job.changed.notify_all()

    async def events_after(self, job: ChatJob, after: int) -> list[ChatJobEvent]:
        async with job.changed:
            return [event for event in job.events if event.seq > after]

    async def events_after_with_snapshot(
        self,
        job: ChatJob,
        after: int,
    ) -> tuple[list[ChatJobEvent], dict[str, Any], list[ChatJobEvent]]:
        async with job.changed:
            events = [event for event in job.events if event.seq > after]
            snapshot = job.snapshot()
            live_events = _current_webchat_live_events(job, after, events)
            return events, snapshot, live_events

    async def update_agent_stage(
        self, job: ChatJob, payload: dict[str, Any]
    ) -> ChatJobEvent | None:
        event_payload = _sanitize_webchat_event_payload("agent_stage", payload)
        event_time = time.time()
        call_id = _webchat_tool_event_key(event_payload)
        stage_key = str(event_payload.get("stage") or "").strip()
        if not stage_key:
            return None
        async with job.changed:
            previous_stage = job.agent_current_stage.get(call_id)
            if previous_stage != stage_key:
                job.agent_current_stage[call_id] = stage_key
                job.agent_stage_started_at[call_id] = event_time
            started_at = job.agent_stage_started_at.get(call_id, event_time)
            event_payload["started_at"] = started_at
            event_payload["stage_elapsed_ms"] = max(
                0, int((event_time - started_at) * 1000)
            )
            event_payload["elapsed_ms"] = _job_elapsed_ms(job, event_time)
            event_payload["job_id"] = job.job_id
            job.agent_stage_payloads[call_id] = dict(event_payload)
            return self._append_event_locked(job, "agent_stage", event_payload)

    async def append_lifecycle_event(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> ChatJobEvent | None:
        if event not in _WEBCHAT_LIFECYCLE_EVENTS:
            return None
        event_payload = _sanitize_webchat_event_payload(event, payload)
        event_time = time.time()
        output_event = str(event_payload.get("_event", event) or event)
        tool_key = _webchat_tool_event_key(event_payload)
        logger.debug(
            "[RuntimeAPI][WebChat] 生命周期事件: job_id=%s conversation_id=%s event=%s tool_key=%s",
            job.job_id,
            job.conversation_id,
            output_event,
            tool_key,
        )
        async with job.changed:
            if output_event in {"tool_start", "agent_start"}:
                job.tool_started_at[tool_key] = event_time
                event_payload["started_at"] = event_time
                job.tool_start_payloads[tool_key] = dict(event_payload)
            elif output_event in {"tool_end", "agent_end"}:
                lifecycle_started_at = job.tool_started_at.get(tool_key)
                job.tool_started_at.pop(tool_key, 0.0)
                job.tool_start_payloads.pop(tool_key, None)
                if lifecycle_started_at is not None:
                    event_payload["duration_ms"] = max(
                        0, int((event_time - lifecycle_started_at) * 1000)
                    )
                if output_event == "agent_end":
                    job.agent_current_stage.pop(tool_key, None)
                    job.agent_stage_started_at.pop(tool_key, None)
                    job.agent_stage_payloads.pop(tool_key, None)
            event_payload["elapsed_ms"] = _job_elapsed_ms(job, event_time)
            event_payload["job_id"] = job.job_id
            return self._append_event_locked(job, event, event_payload)

    async def append_action_event(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> ChatJobEvent | None:
        if event not in _WEBCHAT_ACTION_EVENTS:
            return None
        event_time = time.time()
        event_payload = _sanitize_webchat_event_payload(event, payload)
        event_payload["elapsed_ms"] = _job_elapsed_ms(job, event_time)
        event_payload["job_id"] = job.job_id
        async with job.changed:
            return self._append_event_locked(job, event, event_payload)

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
        logger.info(
            "[RuntimeAPI][WebChat] job 开始: job_id=%s conversation_id=%s text_len=%s",
            job.job_id,
            job.conversation_id,
            len(job.text),
        )
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
            # 将输出中的内联媒体（[CQ:image,file=base64://…]、file:// 等）注册为附件并
            # 统一为 <attachment uid/>，避免把 base64/本地路径写入历史或喂给后续 LLM；
            # 客户端按 UID 经 /api/v1/chat/attachments/{uid}/preview 拉取渲染。
            output_text, output_attachments = await _normalize_webchat_output(
                content,
                registry=self._ctx.ai.attachment_registry,
                scope_key=webui_scope_key,
                resolve_image_url=self._ctx.onebot.get_image,
                get_forward_messages=self._ctx.onebot.get_forward_msg,
            )
            if not output_text.strip() and not output_attachments:
                return
            outputs.append(output_text)
            job.outputs.append(output_text)
            job.history_outputs.append(output_text)
            job.history_attachments.extend(output_attachments)
            logger.info(
                "[RuntimeAPI][WebChat] job 输出消息: job_id=%s conversation_id=%s text_len=%s attachments=%s",
                job.job_id,
                job.conversation_id,
                len(output_text),
                len(output_attachments),
            )
            now = time.time()
            await self._append_event(
                job,
                "message",
                {
                    "content": output_text,
                    "attachments": [
                        _chat_attachment_response_metadata(
                            {**ref, "id": str(ref.get("uid") or "")}
                        )
                        for ref in output_attachments
                    ],
                    "job_id": job.job_id,
                    "elapsed_ms": _job_elapsed_ms(job, now),
                    "parent_webchat_call_id": _current_webchat_agent_call_id(job),
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
            if event in _WEBCHAT_AGENT_STAGE_EVENTS:
                await self.update_agent_stage(job, payload)
                return
            if event in _WEBCHAT_ACTION_EVENTS:
                await self.append_action_event(job, event, payload)
                return
            if event not in _WEBCHAT_LIFECYCLE_EVENTS:
                return
            await self.append_lifecycle_event(job, event, payload)

        try:
            run_kwargs: dict[str, Any] = {
                "text": job.text,
                "send_output": _capture_private_message,
            }
            if "webchat_event_callback" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["webchat_event_callback"] = _webchat_event_callback
            if "conversation_store" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["conversation_store"] = self.conversation_store
            if "conversation_id" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["conversation_id"] = job.conversation_id
            if "input_attachments" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["input_attachments"] = job.user_history_attachments
            if "input_references" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["input_references"] = job.user_history_references
            if "record_input_history" in inspect.signature(run_webui_chat).parameters:
                run_kwargs["record_input_history"] = not job.user_history_pre_recorded
            await self._append_stage(job, "processing")
            mode = await run_webui_chat(self._ctx, **run_kwargs)
            job.mode = mode
            job.status = "done"
            self._mark_job_finished(job)
            logger.info(
                "[RuntimeAPI][WebChat] job 完成: job_id=%s conversation_id=%s mode=%s duration_ms=%s outputs=%s",
                job.job_id,
                job.conversation_id,
                mode,
                job.duration_ms,
                len(outputs),
            )
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
            logger.info(
                "[RuntimeAPI][WebChat] job 已取消: job_id=%s conversation_id=%s duration_ms=%s",
                job.job_id,
                job.conversation_id,
                job.duration_ms,
            )
            await self._append_cancelled_event_once(job)
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
                await self.maybe_schedule_title_generation(job.conversation_id)
            except Exception as exc:
                logger.exception(
                    "[RuntimeAPI] chat job history finalize failed: %s", exc
                )
                job.history_finalized = True
            async with job.changed:
                job.done.set()
                job.changed.notify_all()

    async def _append_event(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> ChatJobEvent:
        async with job.changed:
            return self._append_event_locked(job, event, payload)

    async def _append_cancelled_event_once(self, job: ChatJob) -> None:
        async with job.changed:
            if any(
                event.event == "error" and event.payload.get("error") == "cancelled"
                for event in job.events
            ):
                return
            self._append_event_locked(
                job,
                "error",
                {
                    "error": "cancelled",
                    "job_id": job.job_id,
                    "duration_ms": job.duration_ms,
                },
            )

    def _append_event_locked(
        self, job: ChatJob, event: str, payload: dict[str, Any]
    ) -> ChatJobEvent:
        payload_copy = dict(payload)
        normalized_event = str(payload_copy.pop("_event", event) or event)
        payload_copy.setdefault("conversation_id", job.conversation_id)
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
                job.webchat_events = job.webchat_events[-_CHAT_JOB_EVENT_BUFFER_LIMIT:]
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
            "conversation_id": job.conversation_id,
            "stage": stage_key,
            "started_at": now,
            "elapsed_ms": _job_elapsed_ms(job, now),
        }
        detail_text = _preview(detail, 120)
        if detail_text:
            payload["detail"] = detail_text
        async with job.changed:
            job.current_stage = stage_key
            job.current_stage_detail = detail_text
            job.current_stage_started_at = now
            return self._append_event_locked(job, "stage", payload)

    def _mark_job_finished(self, job: ChatJob) -> None:
        now = time.time()
        job.finished_at = now
        job.duration_ms = _job_elapsed_ms(job, now)
        job.updated_at = now

    async def _finalize_job_history(self, job: ChatJob) -> None:
        async with job.history_lock:
            if job.history_finalized:
                logger.debug(
                    "[RuntimeAPI][WebChat] job 历史已落盘，跳过: job_id=%s conversation_id=%s",
                    job.job_id,
                    job.conversation_id,
                )
                return
            text_content = "\n\n".join(job.history_outputs).strip()
            webchat = _build_webchat_history_payload(job)
            if text_content or webchat["events"]:
                await self.conversation_store.append_message(
                    job.conversation_id,
                    role="bot",
                    text_content=text_content,
                    display_name="Bot",
                    user_name="Bot",
                    attachments=job.history_attachments or None,
                    webchat=webchat,
                )
                logger.info(
                    "[RuntimeAPI][WebChat] job 历史落盘: job_id=%s conversation_id=%s text_len=%s events=%s attachments=%s",
                    job.job_id,
                    job.conversation_id,
                    len(text_content),
                    len(webchat["events"]),
                    len(job.history_attachments),
                )
            else:
                logger.info(
                    "[RuntimeAPI][WebChat] job 无需落盘 bot 历史: job_id=%s conversation_id=%s",
                    job.job_id,
                    job.conversation_id,
                )
            job.history_finalized = True

    async def maybe_schedule_title_generation(self, conversation_id: str) -> None:
        async with self._title_schedule_lock:
            if self.conversation_store.title_task_running(conversation_id):
                logger.debug(
                    "[RuntimeAPI][WebChat] 标题生成任务已存在: conversation_id=%s",
                    conversation_id,
                )
                return
            first_pair = await self.conversation_store.first_question_answer(
                conversation_id
            )
            if first_pair is None:
                logger.debug(
                    "[RuntimeAPI][WebChat] 标题生成跳过，缺少首问首答: conversation_id=%s",
                    conversation_id,
                )
                return
            if not await self.conversation_store.mark_title_pending(conversation_id):
                logger.debug(
                    "[RuntimeAPI][WebChat] 标题生成跳过，状态不允许: conversation_id=%s",
                    conversation_id,
                )
                return
            question, answer = first_pair
            basis_hash = webchat_title_basis_hash(question, answer)
            logger.info(
                "[RuntimeAPI][WebChat] 调度标题生成: conversation_id=%s question_len=%s answer_len=%s",
                conversation_id,
                len(question),
                len(answer),
            )

            async def _run_title() -> None:
                try:
                    title = await generate_webchat_title(self._ctx.ai, question, answer)
                    if title:
                        await self.conversation_store.apply_generated_title(
                            conversation_id,
                            title=title,
                            basis_hash=basis_hash,
                        )
                        logger.info(
                            "[RuntimeAPI][WebChat] 标题生成完成: conversation_id=%s title_len=%s",
                            conversation_id,
                            len(title),
                        )
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "[RuntimeAPI] webchat title generation failed: %s", exc
                    )
                await self.conversation_store.mark_title_failed(
                    conversation_id, basis_hash
                )

            task = asyncio.create_task(
                _run_title(), name=f"webchat-title:{conversation_id}"
            )
            self.conversation_store.register_title_task(conversation_id, task)


def _job_elapsed_ms(job: ChatJob, now: float | None = None) -> int:
    measured_at = time.time() if now is None else now
    return max(0, int((measured_at - job.created_at) * 1000))


def _stage_elapsed_ms(job: ChatJob, now: float | None = None) -> int:
    if job.current_stage_started_at <= 0:
        return 0
    measured_at = time.time() if now is None else now
    return max(0, int((measured_at - job.current_stage_started_at) * 1000))


def _current_webchat_live_events(
    job: ChatJob,
    after: int,
    events: list[ChatJobEvent],
) -> list[ChatJobEvent]:
    live_events: list[ChatJobEvent] = []
    current_stage_event = job.current_stage_event()
    if (
        current_stage_event is not None
        and current_stage_event.seq >= after
        and not any(
            existing.event == current_stage_event.event
            and existing.payload.get("stage")
            == current_stage_event.payload.get("stage")
            for existing in events
        )
    ):
        live_events.append(current_stage_event)
    live_events.extend(
        event
        for event in job.current_agent_stage_events()
        if event.seq >= after
        and not any(
            existing.event == event.event
            and existing.payload.get("webchat_call_id")
            == event.payload.get("webchat_call_id")
            and existing.payload.get("stage") == event.payload.get("stage")
            for existing in events
        )
    )
    return live_events


def _current_webchat_agent_call_id(job: ChatJob) -> str:
    open_calls: list[tuple[str, bool]] = []
    for item in job.webchat_events:
        if item.event not in _WEBCHAT_LIFECYCLE_EVENTS:
            continue
        payload = item.payload
        call_id = _webchat_tool_event_key(payload)
        if not call_id:
            continue
        if item.event in {"tool_start", "agent_start"}:
            open_calls.append((call_id, bool(payload.get("is_agent"))))
            continue
        if item.event in {"tool_end", "agent_end"}:
            for index in range(len(open_calls) - 1, -1, -1):
                if open_calls[index][0] == call_id:
                    open_calls.pop(index)
                    break
    for call_id, is_agent in reversed(open_calls):
        if is_agent:
            return call_id
    return ""


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
    redacted = _redact_preview_value(value)
    if isinstance(redacted, dict | list):
        text = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
    else:
        text = _redact_secret_text(str(redacted or ""))
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _preview_existing_text(raw: Any, limit: int = _PREVIEW_LIMIT) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    with suppress(json.JSONDecodeError, TypeError, ValueError):
        return _preview(json.loads(text), limit)
    return _preview(text, limit)


def _chat_attachment_max_upload_size_bytes(ctx: RuntimeAPIContext) -> int:
    cfg = ctx.config_getter()
    raw_max_size_mb = getattr(cfg, "messages_send_url_file_max_size_mb", None)
    max_size_mb = 100 if raw_max_size_mb is None else int(raw_max_size_mb)
    return max(1, max_size_mb) * 1024 * 1024


def _chat_attachment_blob_path(attachment_id: str) -> Path:
    return _CHAT_ATTACHMENT_BLOB_DIR / attachment_id


def _chat_attachment_meta_path(attachment_id: str) -> Path:
    return _CHAT_ATTACHMENT_META_DIR / f"{attachment_id}.json"


def _valid_chat_attachment_id(raw: Any) -> str:
    attachment_id = str(raw or "").strip()
    if not _CHAT_ATTACHMENT_ID_PATTERN.fullmatch(attachment_id):
        return ""
    return attachment_id


def _chat_attachment_response_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    attachment_id = str(raw.get("id") or "").strip()
    media_type = str(raw.get("media_type") or "application/octet-stream").strip()
    kind = str(raw.get("kind") or "").strip() or (
        "image" if media_type.startswith("image/") else "file"
    )
    metadata: dict[str, Any] = {
        "id": attachment_id,
        "uid": attachment_id,
        "name": str(raw.get("name") or "attachment"),
        "display_name": str(raw.get("display_name") or raw.get("name") or "attachment"),
        "size": int(raw.get("size") or 0),
        "media_type": media_type,
        "kind": kind,
        "sha256": str(raw.get("sha256") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "download_url": f"/api/v1/chat/attachments/{attachment_id}",
        "discarded": False,
        "source_kind": "runtime_webchat_attachment",
        "source_ref": f"/api/v1/chat/attachments/{attachment_id}",
    }
    if media_type.startswith("image/"):
        metadata["preview_url"] = f"/api/v1/chat/attachments/{attachment_id}/preview"
    return metadata


async def _load_chat_attachment_metadata(attachment_id: str) -> dict[str, Any] | None:
    clean_id = _valid_chat_attachment_id(attachment_id)
    if not clean_id:
        return None
    raw = await async_io.read_json(_chat_attachment_meta_path(clean_id), use_lock=True)
    if not isinstance(raw, dict):
        return None
    raw["id"] = clean_id
    return _chat_attachment_response_metadata(raw)


async def _load_chat_attachment_from_request(
    request: web.Request,
) -> dict[str, Any] | None:
    attachment_id = _valid_chat_attachment_id(
        request.match_info.get("attachment_id", "")
    )
    if not attachment_id:
        return None
    return await _load_chat_attachment_metadata(attachment_id)


def _content_disposition_attachment(display_name: str) -> str:
    clean_name = _sanitize_chat_attachment_name(display_name)
    ascii_name = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in clean_name
    ).strip("_")
    if not ascii_name:
        ascii_name = "attachment"
    return f'attachment; filename="{ascii_name}"'


def _sanitize_chat_attachment_name(raw_name: str) -> str:
    raw_text = unquote(str(raw_name or "").strip() or "attachment")
    without_controls = "".join(
        char for char in raw_text if ord(char) >= 32 and ord(char) != 127
    )
    name = (
        Path(without_controls.replace("\\", "/").strip() or "attachment").name
        or "attachment"
    )
    if len(name) <= _CHAT_ATTACHMENT_MAX_NAME_LENGTH:
        return name
    suffix = "".join(Path(name).suffixes[-2:]) or Path(name).suffix
    suffix = suffix if len(suffix) <= 16 else ""
    return f"attachment{suffix}"


def _normalize_sensitive_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").lower())


def _is_sensitive_preview_key(key: Any) -> bool:
    normalized = _normalize_sensitive_key(key)
    if not normalized:
        return False
    if normalized in _SENSITIVE_KEY_EXACT:
        return True
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _redact_secret_text(text: str) -> str:
    redacted = str(text or "")
    redacted = _SECRET_TEXT_PATTERNS[0].sub(
        lambda match: (
            f"{match.group(1)}: {match.group(2) or ''}{_REDACTED_PREVIEW_VALUE}"
        ),
        redacted,
    )
    redacted = _SECRET_TEXT_PATTERNS[1].sub(
        lambda match: (
            f"{match.group(1)}={match.group(2)}"
            f"{_REDACTED_PREVIEW_VALUE}{match.group(2) or ''}"
        ),
        redacted,
    )
    redacted = _SECRET_TEXT_PATTERNS[2].sub(
        lambda match: f"{match.group(1)} {_REDACTED_PREVIEW_VALUE}",
        redacted,
    )
    return redacted


def _redact_preview_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted_dict: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            redacted_dict[text_key] = (
                _REDACTED_PREVIEW_VALUE
                if _is_sensitive_preview_key(text_key)
                else _redact_preview_value(item)
            )
        return redacted_dict
    if isinstance(value, list):
        return [_redact_preview_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_preview_value(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_text(value)
    return value


def _redact_webchat_display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("arguments_preview", "result_preview", "current_stage_detail"):
        if key in result:
            result[key] = _preview_existing_text(result.get(key))
    if "detail" in result:
        result["detail"] = _preview_existing_text(result.get("detail"), 160)
    return result


def _redact_webchat_display_tree(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_webchat_display_tree(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        str(key): _redact_webchat_display_tree(item) for key, item in value.items()
    }
    return _redact_webchat_display_payload(result)


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
            "result_preview": _preview(result),
            "is_agent": is_agent,
            **_webchat_payload_lineage(payload),
            **({"ui_hint": ui_hint} if ui_hint else {}),
        }
    if event == "agent_stage":
        stage = str(payload.get("stage") or payload.get("key") or "").strip()
        agent_name = str(payload.get("agent_name") or payload.get("name") or "")
        call_id = str(payload.get("webchat_call_id") or "").strip()
        parent_call_id = str(payload.get("parent_webchat_call_id") or "").strip()
        if not call_id:
            call_id = parent_call_id or agent_name or "agent"
            payload = {**payload, "webchat_call_id": call_id}
        return {
            "stage": stage,
            "detail": _preview(payload.get("detail"), 160),
            "status": str(payload.get("status") or "running"),
            "name": agent_name,
            "agent_name": agent_name,
            "is_agent": True,
            **_webchat_payload_lineage(payload),
        }
    if event in _WEBCHAT_ACTION_EVENTS:
        clean_payload = {
            str(key): value for key, value in payload.items() if key != "arguments"
        }
        redacted_payload = _redact_preview_value(clean_payload)
        return redacted_payload if isinstance(redacted_payload, dict) else {}
    return {key: value for key, value in payload.items() if key != "arguments"}


def _build_webchat_history_payload(job: ChatJob) -> dict[str, Any]:
    events = _finalize_webchat_history_events(job)
    return {
        "display_only": True,
        "job_id": job.job_id,
        "conversation_id": job.conversation_id,
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
        "current_stage": str(payload.get("current_stage") or "").strip(),
        "current_stage_detail": str(payload.get("current_stage_detail") or "").strip(),
        "current_stage_elapsed_ms": payload.get("current_stage_elapsed_ms"),
        "depth": payload.get("depth", 0),
        "agent_path": payload.get("agent_path")
        if isinstance(payload.get("agent_path"), list)
        else [],
        "children": [],
        "timeline": [],
    }


def _webchat_event_call_id(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return ""
    call_id = str(payload.get("webchat_call_id") or "").strip()
    return call_id or _legacy_webchat_tool_event_key(payload)


def _history_agent_stage_seq(event: dict[str, Any]) -> int:
    if str(event.get("event") or "") != "agent_stage":
        return _webchat_event_seq(event)
    seq = _webchat_event_seq(event)
    return max(0, seq - 1)


def _build_webchat_call_graph(
    events: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in events:
        event = str(item.get("event") or "")
        if event not in _WEBCHAT_LIFECYCLE_EVENTS and event != "agent_stage":
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
            if event == "agent_stage":
                insert_after = _history_agent_stage_seq(item)
                insert_at = len(order)
                for index, existing_call_id in enumerate(order):
                    existing = nodes.get(existing_call_id)
                    if existing is None:
                        continue
                    started_seq = int(existing.get("_started_seq", 0) or 0)
                    if started_seq > insert_after:
                        insert_at = index
                        break
                order.insert(insert_at, call_id)
            else:
                order.append(call_id)
        if event == "agent_stage":
            node.update(
                {
                    "current_stage": str(payload.get("stage") or "").strip(),
                    "current_stage_detail": str(payload.get("detail") or "").strip(),
                    "current_stage_elapsed_ms": payload.get("stage_elapsed_ms"),
                    "elapsed_ms": payload.get("elapsed_ms"),
                    "is_agent": True,
                    "name": str(
                        payload.get("agent_name")
                        or payload.get("name")
                        or node.get("name")
                        or ""
                    ).strip(),
                }
            )
            continue
        if event in {"tool_start", "agent_start"}:
            node.update(_call_preview_node({**payload, "webchat_call_id": call_id}))
            node["status"] = "running"
            node["_started_seq"] = _webchat_event_seq(item)
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
    _populate_webchat_node_timelines(nodes, events)
    for node in nodes.values():
        node.pop("_started_seq", None)
    return nodes, order, roots


def _build_webchat_call_tree(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _nodes, _order, roots = _build_webchat_call_graph(events)
    return roots


def _webchat_event_seq(event: dict[str, Any]) -> int:
    seq_raw = event.get("seq", 0)
    try:
        return max(0, int(seq_raw))
    except (TypeError, ValueError):
        return 0


def _webchat_message_timeline_item(
    *,
    event: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    content = str(payload.get("content") or payload.get("message") or "")
    if not content:
        return None
    return {
        "type": "message",
        "seq": _webchat_event_seq(event),
        "content": content,
        "elapsed_ms": payload.get("elapsed_ms"),
    }


def _webchat_agent_stage_timeline_item(
    *,
    event: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    stage = str(payload.get("stage") or "").strip()
    if not stage:
        return None
    detail = str(payload.get("detail") or "").strip()
    return {
        "type": "stage",
        "seq": _webchat_event_seq(event),
        "stage": stage,
        "detail": detail,
        "elapsed_ms": payload.get("elapsed_ms"),
        "stage_elapsed_ms": payload.get("stage_elapsed_ms"),
    }


def _populate_webchat_node_timelines(
    nodes: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    emitted_child_calls: set[str] = set()
    for node in nodes.values():
        node["timeline"] = []
    for item in events:
        event = str(item.get("event") or "")
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if event == "message":
            parent_id = str(payload.get("parent_webchat_call_id") or "").strip()
            parent = nodes.get(parent_id)
            if parent is None:
                continue
            message_item = _webchat_message_timeline_item(event=item, payload=payload)
            if message_item is not None:
                parent.setdefault("timeline", []).append(message_item)
            continue
        if event == "agent_stage":
            call_id = _webchat_event_call_id(item)
            parent = nodes.get(call_id)
            if parent is None:
                continue
            stage_item = _webchat_agent_stage_timeline_item(event=item, payload=payload)
            if stage_item is not None:
                parent.setdefault("timeline", []).append(stage_item)
            continue
        if event not in _WEBCHAT_LIFECYCLE_EVENTS:
            continue
        call_id = _webchat_event_call_id(item)
        if not call_id or call_id in emitted_child_calls:
            continue
        call_node = nodes.get(call_id)
        if call_node is None:
            continue
        parent_id = str(call_node.get("parent_webchat_call_id") or "").strip()
        call_parent = nodes.get(parent_id)
        if call_parent is None:
            continue
        emitted_child_calls.add(call_id)
        call_parent.setdefault("timeline", []).append(
            {"type": "call", "seq": _webchat_event_seq(item), "call": call_node}
        )
    for node in nodes.values():
        timeline = node.get("timeline")
        if isinstance(timeline, list):
            timeline.sort(key=lambda entry: int(entry.get("seq", 0) or 0))


def _build_webchat_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes, _order, _roots = _build_webchat_call_graph(events)
    emitted_calls: set[str] = set()
    timeline: list[dict[str, Any]] = []
    for item in events:
        event = str(item.get("event") or "")
        payload = item.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if event == "message":
            if str(payload.get("parent_webchat_call_id") or "").strip():
                continue
            message_item = _webchat_message_timeline_item(event=item, payload=payload)
            if message_item is not None:
                timeline.append(message_item)
            continue
        if event == "agent_stage":
            call_id = _webchat_event_call_id(item)
            if call_id and call_id in nodes:
                continue
            stage_item = _webchat_agent_stage_timeline_item(event=item, payload=payload)
            if stage_item is not None:
                timeline.append(stage_item)
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
        timeline.append({"type": "call", "seq": _webchat_event_seq(item), "call": node})
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
        events.append(
            {
                "seq": seq,
                "event": event,
                "payload": _redact_webchat_display_payload(payload),
            }
        )
    return events


def _webchat_history_calls(webchat: Any) -> list[dict[str, Any]]:
    if not isinstance(webchat, dict):
        return []
    raw_calls = webchat.get("calls")
    if isinstance(raw_calls, list):
        return [
            _redact_webchat_display_tree(item)
            for item in raw_calls
            if isinstance(item, dict)
        ]
    return _build_webchat_call_tree(_webchat_history_events(webchat))


def _webchat_history_timeline(webchat: Any) -> list[dict[str, Any]]:
    if not isinstance(webchat, dict):
        return []
    raw_timeline = webchat.get("timeline")
    if isinstance(raw_timeline, list):
        return [
            _redact_webchat_display_tree(item)
            for item in raw_timeline
            if isinstance(item, dict)
        ]
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


def _query_conversation_id(request: web.Request) -> str:
    return str(request.query.get("conversation_id", "") or "").strip()


def _body_conversation_id(body: dict[str, Any]) -> str:
    return str(body.get("conversation_id", "") or "").strip()


def _is_structured_chat_message(raw: Any) -> bool:
    return isinstance(raw, dict)


async def _parse_chat_job_message(
    body: dict[str, Any],
    *,
    conversation_id: str,
) -> StructuredChatMessage:
    raw_message = body.get("message")
    if not isinstance(raw_message, dict):
        return StructuredChatMessage(
            text=str(raw_message or "").strip(),
            attachments=[],
            references=[],
        )
    text = str(raw_message.get("text") or "").strip()
    references = _normalize_chat_references(raw_message.get("references"))
    attachments = await _normalize_chat_attachment_ids(
        raw_message.get("attachment_ids")
    )
    reference_prefix = _references_to_prompt_text(references)
    parts = [part for part in [reference_prefix, text] if part]
    return StructuredChatMessage(
        text="\n\n".join(parts).strip(),
        attachments=attachments,
        references=references,
    )


def _normalize_chat_references(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    references: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_message_id = str(item.get("source_message_id") or "").strip()
        selected_text = str(item.get("selected_text") or "").strip()
        kind = str(item.get("kind") or "message").strip() or "message"
        if not source_message_id and not selected_text:
            continue
        references.append(
            {
                "kind": kind,
                "source_message_id": source_message_id,
                "selected_text": selected_text,
            }
        )
    return references


def _references_to_prompt_text(references: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in references:
        source_message_id = str(item.get("source_message_id") or "").strip()
        selected_text = str(item.get("selected_text") or "").strip()
        header = (
            f"> 引用 message:{source_message_id}" if source_message_id else "> 引用"
        )
        if selected_text:
            quote_lines = "\n".join(f"> {line}" for line in selected_text.splitlines())
            blocks.append(f"{header}\n{quote_lines}")
        else:
            blocks.append(header)
    return "\n\n".join(blocks).strip()


async def _normalize_chat_attachment_ids(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_id in raw:
        attachment_id = _valid_chat_attachment_id(raw_id)
        if not attachment_id or attachment_id in seen:
            continue
        metadata = await _load_chat_attachment_metadata(attachment_id)
        if metadata is None:
            raise ChatAttachmentNotFoundError(attachment_id)
        seen.add(attachment_id)
        ref: dict[str, str] = {
            "uid": attachment_id,
            "kind": str(metadata.get("kind") or "file"),
            "media_type": str(metadata.get("media_type") or "application/octet-stream"),
            "display_name": str(metadata.get("name") or "attachment"),
            "source_kind": "runtime_webchat_attachment",
            "source_ref": str(metadata.get("download_url") or ""),
        }
        preview_url = str(metadata.get("preview_url") or "").strip()
        if preview_url:
            ref["render_source"] = preview_url
        attachments.append(ref)
    return attachments


async def _resolve_conversation_id(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    *,
    raw_conversation_id: str = "",
    create_default: bool = True,
) -> str:
    await job_manager.conversation_store.ensure_ready(ctx.history_manager)
    conversation_id = str(raw_conversation_id or "").strip()
    if conversation_id:
        conversation = await job_manager.conversation_store.get_conversation(
            conversation_id
        )
        if conversation is None:
            raise KeyError(conversation_id)
        return str(conversation["id"])
    if not create_default:
        return ""
    conversation = await job_manager.conversation_store.get_conversation(
        _DEFAULT_CONVERSATION_ID
    )
    if conversation is None:
        conversation = (
            await job_manager.conversation_store.ensure_default_conversation()
        )
    return str(conversation["id"])


async def _history_record_to_item(
    item: dict[str, Any],
    *,
    attachment_registry: Any | None = None,
    scope_key: str | None = None,
) -> dict[str, Any] | None:
    content = str(item.get("message", "")).strip()
    webchat = item.get("webchat")
    webchat_events = _webchat_history_events(webchat)
    attachments = await _history_attachments(
        item.get("attachments"),
        attachment_registry=attachment_registry,
        scope_key=scope_key,
    )
    if not content and not webchat_events and not attachments:
        return None
    display_name = str(item.get("display_name", "")).strip().lower()
    role = "bot" if display_name == "bot" else "user"
    mapped: dict[str, Any] = {
        "message_id": str(item.get("message_id") or "").strip(),
        "role": role,
        "content": content,
        "timestamp": str(item.get("timestamp", "") or "").strip(),
    }
    if attachments:
        mapped["attachments"] = attachments
    references = _history_references(item.get("references"))
    if references:
        mapped["references"] = references
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


def _history_references(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    references: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "message").strip() or "message"
        source_message_id = str(item.get("source_message_id") or "").strip()
        selected_text = str(item.get("selected_text") or "").strip()
        if not source_message_id and not selected_text:
            continue
        references.append(
            {
                "kind": kind,
                "source_message_id": source_message_id,
                "selected_text": selected_text,
            }
        )
    return references


async def _history_attachments(
    raw: Any,
    *,
    attachment_registry: Any | None = None,
    scope_key: str | None = None,
) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    attachments: list[dict[str, str]] = []
    if attachment_registry is not None:
        load = getattr(attachment_registry, "load", None)
        if callable(load):
            with suppress(Exception):
                await load()
    for item in raw:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid", "") or "").strip()
        if not uid:
            continue
        media_type = str(item.get("media_type") or item.get("kind") or "file").strip()
        kind = str(item.get("kind") or media_type or "file").strip()
        ref: dict[str, str] = {
            "uid": uid,
            "kind": kind or "file",
            "media_type": media_type or kind or "file",
            "display_name": str(item.get("display_name", "") or ""),
        }
        for key in ("source_kind", "source_ref", "semantic_kind", "description"):
            value = str(item.get(key, "") or "").strip()
            if value:
                ref[key] = value
        resolved = await _resolve_history_attachment(
            uid,
            attachment_registry=attachment_registry,
            scope_key=scope_key,
        )
        if resolved is not None:
            ref.update(await _history_attachment_render_fields(resolved))
        # 补充 preview_url / download_url，供客户端渲染附件卡片
        ref["download_url"] = f"/api/v1/chat/attachments/{uid}"
        if media_type.startswith("image/"):
            ref["preview_url"] = f"/api/v1/chat/attachments/{uid}/preview"
        attachments.append(ref)
    return attachments


async def _resolve_history_attachment(
    uid: str,
    *,
    attachment_registry: Any | None,
    scope_key: str | None,
) -> Any | None:
    if attachment_registry is None:
        return None
    try:
        resolve_async = getattr(attachment_registry, "resolve_async", None)
        if callable(resolve_async):
            return await resolve_async(uid, scope_key)
        resolve = getattr(attachment_registry, "resolve", None)
        if callable(resolve):
            return resolve(uid, scope_key)
    except Exception as exc:
        logger.debug(
            "[RuntimeAPI] resolve history attachment failed uid=%s err=%s", uid, exc
        )
    return None


async def _history_attachment_render_fields(record: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    source_ref = str(getattr(record, "source_ref", "") or "").strip()
    if source_ref:
        fields["source_ref"] = source_ref
    local_path = str(getattr(record, "local_path", "") or "").strip()
    media_type = str(getattr(record, "media_type", "") or "").strip().lower()
    if media_type == "image":
        if local_path:
            try:
                path = Path(local_path)
                if await async_io.is_file(path):
                    fields["render_source"] = path.resolve().as_uri()
            except OSError:
                pass
        if "render_source" not in fields and source_ref:
            fields["render_source"] = source_ref
    if source_ref.isalnum():
        fields["file_id"] = source_ref
    return fields


async def run_webui_chat(
    ctx: RuntimeAPIContext,
    *,
    text: str,
    send_output: Callable[[int, str], Awaitable[None]],
    webchat_event_callback: Callable[[str, dict[str, Any]], Awaitable[None]]
    | None = None,
    conversation_store: WebChatConversationStore | None = None,
    conversation_id: str | None = None,
    input_attachments: list[dict[str, str]] | None = None,
    input_references: list[dict[str, Any]] | None = None,
    record_input_history: bool = True,
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
    resolved_conversation_id = (
        str(conversation_id or _DEFAULT_CONVERSATION_ID).strip()
        or _DEFAULT_CONVERSATION_ID
    )
    store = conversation_store or WebChatConversationStore()
    await store.ensure_ready(ctx.history_manager)
    logger.info(
        "[RuntimeAPI][WebChat] 开始处理输入: conversation_id=%s text_len=%s",
        resolved_conversation_id,
        len(text),
    )
    if conversation_id:
        existing_conversation = await store.get_conversation(resolved_conversation_id)
        if existing_conversation is None:
            raise KeyError(resolved_conversation_id)
    elif resolved_conversation_id == _DEFAULT_CONVERSATION_ID:
        await store.ensure_default_conversation()
    history_adapter = store.adapter(resolved_conversation_id)
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
    all_input_attachments = [
        *registered_input.attachments,
        *list(input_attachments or []),
    ]
    normalized_references = list(input_references or [])
    logger.info(
        "[RuntimeAPI][WebChat] 输入附件注册完成: conversation_id=%s normalized_len=%s attachments=%s",
        resolved_conversation_id,
        len(normalized_text),
        len(all_input_attachments),
    )
    if record_input_history:
        await emit_stage("recording_history")
        await store.append_message(
            resolved_conversation_id,
            role="user",
            text_content=normalized_text,
            display_name=_VIRTUAL_USER_NAME,
            user_name=_VIRTUAL_USER_NAME,
            attachments=all_input_attachments,
            references=normalized_references or None,
        )

    command = ctx.command_dispatcher.parse_command(normalized_text)
    if command:
        logger.info(
            "[RuntimeAPI][WebChat] 分发私聊命令: conversation_id=%s command=%s",
            resolved_conversation_id,
            getattr(command, "name", ""),
        )
        await emit_stage("running_command")
        await ctx.command_dispatcher.dispatch_private(
            user_id=_VIRTUAL_USER_ID,
            sender_id=permission_sender_id,
            command=command,
            send_private_callback=send_output,
            is_webui_session=True,
        )
        await emit_stage("command_done")
        logger.info(
            "[RuntimeAPI][WebChat] 私聊命令完成: conversation_id=%s",
            resolved_conversation_id,
        )
        return "command"

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    attachment_xml = (
        f"\n{attachment_refs_to_xml(all_input_attachments)}"
        if all_input_attachments
        else ""
    )
    message_xml = format_webchat_message_xml(
        normalized_text, attachment_xml, current_time
    )
    full_question = f"""{message_xml}

【WebUI 会话】
这是一条来自 WebUI 控制台的会话请求。
会话身份：虚拟用户 system(42)。
权限等级：superadmin（你可按最高管理权限处理）。
WebUI 支持完整 Markdown 渲染和简单安全 HTML。复杂 HTML、包含 JS/CSS 的页面、可运行示例或较长代码必须放进 fenced code block；完整 HTML 页面请优先使用 ```html 代码框，方便 WebUI 的运行按钮预览。
需要输出代码时，优先在当前聊天消息中直接给出，不要为了普通代码片段调用文件生成或文件发送工具；只有用户明确要求文件交付、内容长到不适合聊天展示，或确需附件工作流时才使用文件。所有代码都必须使用 fenced code block，并始终标明语言或类型，例如 ```python、```javascript、```html、```bash、```text；不确定语言时使用 ```text。
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
            history_manager=history_adapter,
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
        history_manager = history_adapter  # noqa: F841
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
        logger.info(
            "[RuntimeAPI][WebChat] 调用 AI: conversation_id=%s prompt_len=%s",
            resolved_conversation_id,
            len(full_question),
        )
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
                "webchat_conversation_id": resolved_conversation_id,
                "webchat_event_callback": webchat_event_callback,
            },
        )

    final_reply = str(result or "").strip()
    if final_reply:
        await send_output(_VIRTUAL_USER_ID, final_reply)

    logger.info(
        "[RuntimeAPI][WebChat] AI 调用结束: conversation_id=%s final_reply_len=%s",
        resolved_conversation_id,
        len(final_reply),
    )
    return "chat"


async def chat_attachment_capabilities_handler(
    ctx: RuntimeAPIContext,
    request: web.Request,
) -> Response:
    _ = request
    return web.json_response(
        {
            "max_upload_size_bytes": _chat_attachment_max_upload_size_bytes(ctx),
            "multipart_field": _CHAT_ATTACHMENT_UPLOAD_FIELD,
        }
    )


async def chat_attachment_upload_handler(
    ctx: RuntimeAPIContext,
    request: web.Request,
) -> Response:
    max_size = _chat_attachment_max_upload_size_bytes(ctx)
    try:
        reader = await request.multipart()
    except Exception:
        return _json_error("multipart request required", status=400)

    field_any: Any | None = None
    try:
        while True:
            field = await reader.next()
            if field is None:
                break
            current_field: Any = field
            if getattr(current_field, "name", "") == _CHAT_ATTACHMENT_UPLOAD_FIELD:
                field_any = current_field
                break
    except Exception:
        return _json_error("multipart request required", status=400)

    if field_any is None:
        return _json_error("file field is required", status=400)

    display_name = _sanitize_chat_attachment_name(
        str(getattr(field_any, "filename", "") or "attachment")
    )
    media_type = mimetypes.guess_type(display_name)[0] or "application/octet-stream"
    attachment_id = uuid4().hex
    ensure_dir(_CHAT_ATTACHMENT_BLOB_DIR)
    ensure_dir(_CHAT_ATTACHMENT_META_DIR)
    blob_path = _chat_attachment_blob_path(attachment_id)
    temp_path = blob_path.with_name(f".{attachment_id}.uploading")
    total_size = 0
    digest = hashlib.sha256()
    try:
        async with aiofiles.open(temp_path, "wb") as file_handle:
            while True:
                chunk = await field_any.read_chunk(size=_CHAT_ATTACHMENT_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_size:
                    with suppress(OSError):
                        await asyncio.to_thread(temp_path.unlink)
                    return web.json_response(
                        {"error": "file too large", "max_upload_size_bytes": max_size},
                        status=413,
                    )
                digest.update(chunk)
                await file_handle.write(chunk)
        await asyncio.to_thread(os.replace, temp_path, blob_path)
    except Exception:
        with suppress(OSError):
            await asyncio.to_thread(temp_path.unlink)
        return _json_error("multipart request required", status=400)

    metadata = _chat_attachment_response_metadata(
        {
            "id": attachment_id,
            "name": display_name,
            "size": total_size,
            "media_type": media_type,
            "kind": "image" if media_type.startswith("image/") else "file",
            "sha256": digest.hexdigest(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    await async_io.write_json(
        _chat_attachment_meta_path(attachment_id), metadata, use_lock=True
    )
    return web.json_response(
        {"attachment": metadata},
        status=201,
    )


async def chat_attachment_download_handler(
    ctx: RuntimeAPIContext,
    request: web.Request,
) -> web.StreamResponse:
    _ = ctx
    metadata = await _load_chat_attachment_from_request(request)
    if metadata is None:
        return _json_error("Attachment not found", status=404)
    blob_path = _chat_attachment_blob_path(str(metadata["id"]))
    if not await async_io.is_file(blob_path):
        return _json_error("Attachment not found", status=404)
    headers = {
        "Content-Disposition": _content_disposition_attachment(
            str(metadata.get("name") or "attachment")
        )
    }
    return web.FileResponse(
        path=blob_path,
        headers=headers,
        chunk_size=_CHAT_ATTACHMENT_CHUNK_SIZE,
    )


async def chat_attachment_preview_handler(
    ctx: RuntimeAPIContext,
    request: web.Request,
) -> web.StreamResponse:
    _ = ctx
    metadata = await _load_chat_attachment_from_request(request)
    if metadata is None:
        return _json_error("Attachment not found", status=404)
    media_type = str(metadata.get("media_type") or "").lower()
    if not media_type.startswith("image/"):
        return _json_error("Attachment preview is not available", status=415)
    blob_path = _chat_attachment_blob_path(str(metadata["id"]))
    if not await async_io.is_file(blob_path):
        return _json_error("Attachment not found", status=404)
    return web.FileResponse(
        path=blob_path,
        headers={"Content-Type": media_type},
        chunk_size=_CHAT_ATTACHMENT_CHUNK_SIZE,
    )


async def chat_conversations_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = request
    await job_manager.conversation_store.ensure_ready(ctx.history_manager)
    conversations = await job_manager.conversation_store.list_conversations()
    active_jobs = await job_manager.get_active_jobs()
    active_job = active_jobs[-1] if active_jobs else None
    active_snapshot = (
        await job_manager.snapshot(active_job) if active_job is not None else None
    )
    running_conversation_ids = {job.conversation_id for job in active_jobs}
    for item in conversations:
        conversation_id = str(item.get("id") or "")
        if conversation_id:
            await job_manager.maybe_schedule_title_generation(conversation_id)
            item["is_running"] = conversation_id in running_conversation_ids
    logger.info(
        "[RuntimeAPI][WebChat] 查询会话列表: count=%s active_job=%s",
        len(conversations),
        active_job.job_id if active_job is not None else "",
    )
    return web.json_response(
        {
            "conversations": conversations,
            "active_job": active_snapshot,
            "default_conversation_id": _DEFAULT_CONVERSATION_ID,
            "virtual_user_id": _VIRTUAL_USER_ID,
        }
    )


async def chat_conversation_create_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    await job_manager.conversation_store.ensure_ready(ctx.history_manager)
    try:
        body = await request.json()
    except Exception:
        body = {}
    title = str(body.get("title", "") or "").strip()
    conversation = await job_manager.conversation_store.create_conversation(
        title=title or None,
    )
    logger.info(
        "[RuntimeAPI][WebChat] API 新建会话: conversation_id=%s title_len=%s",
        conversation.get("id", ""),
        len(str(conversation.get("title", "") or "")),
    )
    return web.json_response({"conversation": conversation}, status=201)


async def chat_conversation_update_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    await job_manager.conversation_store.ensure_ready(ctx.history_manager)
    conversation_id = str(request.match_info.get("conversation_id", "") or "").strip()
    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)
    title = str(body.get("title", "") or "").strip()
    try:
        conversation = await job_manager.conversation_store.rename_conversation(
            conversation_id,
            title,
        )
    except KeyError:
        return _json_error("Conversation not found", status=404)
    except ValueError as exc:
        return _json_error(str(exc), status=400)
    logger.info(
        "[RuntimeAPI][WebChat] API 重命名会话: conversation_id=%s title_len=%s",
        conversation_id,
        len(title),
    )
    return web.json_response({"conversation": conversation})


async def chat_conversation_delete_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    await job_manager.conversation_store.ensure_ready(ctx.history_manager)
    conversation_id = str(request.match_info.get("conversation_id", "") or "").strip()
    if await job_manager.has_running_job(conversation_id):
        return _json_error("Chat job is still running", status=409)
    existed = await job_manager.conversation_store.delete_conversation(conversation_id)
    if not existed:
        return _json_error("Conversation not found", status=404)
    logger.info(
        "[RuntimeAPI][WebChat] API 删除会话: conversation_id=%s",
        conversation_id,
    )
    return web.json_response({"success": True, "conversation_id": conversation_id})


async def chat_history_handler(
    ctx: RuntimeAPIContext, job_manager: ChatJobManager, request: web.Request
) -> Response:
    """Return recent WebUI chat history."""

    limit = _parse_limit(request, default=50, maximum=500)
    before = _parse_before(request)
    try:
        conversation_id = await _resolve_conversation_id(
            ctx,
            job_manager,
            raw_conversation_id=_query_conversation_id(request),
        )
        page = await job_manager.conversation_store.get_history_page(
            conversation_id,
            limit=limit,
            before=before,
        )
    except KeyError:
        return _json_error("Conversation not found", status=404)
    items: list[dict[str, Any]] = []
    for record in page.records:
        if isinstance(record, dict):
            mapped = await _history_record_to_item(
                record,
                attachment_registry=getattr(ctx.ai, "attachment_registry", None),
                scope_key=build_attachment_scope(
                    user_id=_VIRTUAL_USER_ID,
                    request_type="private",
                    webui_session=True,
                ),
            )
            if mapped is not None:
                items.append(mapped)
    await job_manager.maybe_schedule_title_generation(conversation_id)
    logger.info(
        "[RuntimeAPI][WebChat] 查询历史: conversation_id=%s returned=%s total=%s has_more=%s before=%s",
        conversation_id,
        len(items),
        page.total,
        page.has_more,
        before,
    )

    return web.json_response(
        {
            "conversation_id": conversation_id,
            "virtual_user_id": _VIRTUAL_USER_ID,
            "permission": "superadmin",
            "count": len(items),
            "items": items,
            "limit": limit,
            "before": before,
            "has_more": page.has_more,
            "next_before": page.next_before,
            "total": page.total,
        }
    )


async def chat_history_clear_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    """Clear WebUI virtual private chat history only."""

    try:
        conversation_id = await _resolve_conversation_id(
            ctx,
            job_manager,
            raw_conversation_id=_query_conversation_id(request),
        )
        cleared = await job_manager.clear_history_when_idle(conversation_id)
    except KeyError:
        return _json_error("Conversation not found", status=404)
    except RuntimeError:
        return _json_error("History manager not ready", status=503)
    if cleared is None:
        return _json_error("Chat job is still running", status=409)
    logger.info(
        "[RuntimeAPI][WebChat] API 清空历史: conversation_id=%s cleared=%s",
        conversation_id,
        cleared,
    )
    return web.json_response(
        {
            "success": True,
            "conversation_id": conversation_id,
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
    try:
        conversation_id = await _resolve_conversation_id(
            ctx,
            job_manager,
            raw_conversation_id=_body_conversation_id(body),
        )
    except KeyError:
        return _json_error("Conversation not found", status=404)

    stream = _to_bool(body.get("stream"))
    logger.info(
        "[RuntimeAPI][WebChat] 收到聊天请求: conversation_id=%s stream=%s text_len=%s",
        conversation_id,
        stream,
        len(text),
    )
    if not stream:
        try:
            job = await job_manager.create_job(text, conversation_id)
        except KeyError:
            return _json_error("Conversation not found", status=404)
        except RuntimeError:
            return _json_error("Chat job is still running", status=409)
        try:
            await job.done.wait()
        except asyncio.CancelledError:
            await job_manager.cancel_job(job.job_id)
            raise
        snapshot = await job_manager.snapshot(job)
        if job.status == "cancelled":
            return _json_error("Chat cancelled", status=409)
        if job.status == "error":
            logger.error("[RuntimeAPI] chat failed: %s", job.error)
            return _json_error("Chat failed", status=502)
        outputs = [
            str(item) for item in snapshot.get("messages", []) if str(item).strip()
        ]
        mode = str(snapshot.get("mode") or job.mode or "chat")
        payload = _build_chat_response_payload(mode, outputs)
        payload["conversation_id"] = conversation_id
        payload["job_id"] = job.job_id
        payload["duration_ms"] = job.duration_ms
        logger.info(
            "[RuntimeAPI][WebChat] 非流式聊天完成: conversation_id=%s mode=%s outputs=%s",
            conversation_id,
            mode,
            len(outputs),
        )
        return web.json_response(payload)

    try:
        job = await job_manager.create_job(text, conversation_id)
    except KeyError:
        return _json_error("Conversation not found", status=404)
    except RuntimeError:
        return _json_error("Chat job is still running", status=409)
    logger.info(
        "[RuntimeAPI][WebChat] SSE 聊天 job 已创建: job_id=%s conversation_id=%s",
        job.job_id,
        conversation_id,
    )
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
                (
                    events,
                    _snapshot,
                    live_events,
                ) = await job_manager.events_after_with_snapshot(job, after)
                for item in events:
                    await _write_sse_event(response, item)
                    after = item.seq
                for live_event in live_events:
                    await _write_sse_event(response, live_event)
                    after = max(after, live_event.seq)
                if events or live_events:
                    if job.done.is_set():
                        break
                    continue
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
    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)
    try:
        conversation_id = await _resolve_conversation_id(
            ctx,
            job_manager,
            raw_conversation_id=_body_conversation_id(body),
        )
        message = await _parse_chat_job_message(body, conversation_id=conversation_id)
        if not message.text and not message.attachments:
            return _json_error("message is required", status=400)
        job = await job_manager.create_job(
            message.text,
            conversation_id,
            user_history_attachments=message.attachments,
            user_history_references=message.references,
            pre_record_user_history=_is_structured_chat_message(body.get("message")),
        )
    except KeyError:
        return _json_error("Conversation not found", status=404)
    except ChatAttachmentNotFoundError:
        return _json_error("Attachment not found", status=404)
    except ValueError as exc:
        return _json_error(str(exc), status=400)
    except RuntimeError:
        return _json_error("Chat job is still running", status=409)
    logger.info(
        "[RuntimeAPI][WebChat] API 创建后台 job: job_id=%s conversation_id=%s text_len=%s",
        job.job_id,
        conversation_id,
        len(message.text),
    )
    return web.json_response(await job_manager.snapshot(job), status=202)


async def chat_job_active_handler(
    ctx: RuntimeAPIContext,
    job_manager: ChatJobManager,
    request: web.Request,
) -> Response:
    _ = ctx
    raw_conversation_id = _query_conversation_id(request)
    jobs = await job_manager.get_active_jobs(raw_conversation_id or None)
    job = jobs[-1] if jobs else None
    snapshot = await job_manager.snapshot(job) if job is not None else None
    snapshots = [await job_manager.snapshot(item) for item in jobs]
    logger.debug(
        "[RuntimeAPI][WebChat] 查询 active job: conversation_id=%s job_id=%s",
        raw_conversation_id,
        job.job_id if job is not None else "",
    )
    return web.json_response({"job": snapshot, "jobs": snapshots})


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
    return web.json_response(await job_manager.snapshot(job))


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
    logger.info(
        "[RuntimeAPI][WebChat] API 取消 job: job_id=%s conversation_id=%s status=%s",
        job.job_id,
        job.conversation_id,
        job.status,
    )
    return web.json_response(await job_manager.snapshot(job))


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
    requested_conversation_id = _query_conversation_id(request)
    if requested_conversation_id and requested_conversation_id != job.conversation_id:
        return _json_error("Job not found", status=404)
    after = _parse_after(request)
    accept_header = str(request.headers.get("Accept", "") or "").strip().lower()
    wants_sse = "text/event-stream" in accept_header
    wants_json = not wants_sse or (
        str(request.query.get("format", "") or "").strip().lower() == "json"
        or "application/json" in accept_header
    )
    if wants_json:
        events, snapshot, live_events = await job_manager.events_after_with_snapshot(
            job, after
        )
        logger.debug(
            "[RuntimeAPI][WebChat] 查询 job 事件: job_id=%s conversation_id=%s after=%s events=%s live_events=%s status=%s",
            job.job_id,
            job.conversation_id,
            after,
            len(events),
            len(live_events),
            job.status,
        )
        return web.json_response(
            {
                "job": snapshot,
                "after": after,
                "last_seq": job.next_seq - 1,
                "events": [
                    {
                        "seq": event.seq,
                        "event": event.event,
                        "payload": dict(event.payload),
                    }
                    for event in [*events, *live_events]
                ],
            }
        )

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
                (
                    events,
                    _snapshot,
                    live_events,
                ) = await job_manager.events_after_with_snapshot(job, after)
                for item in events:
                    await _write_sse_event(response, item)
                    after = item.seq
                for live_event in live_events:
                    await _write_sse_event(response, live_event)
                    after = max(after, live_event.seq)
                if events or live_events:
                    if job.done.is_set():
                        break
                    continue
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
