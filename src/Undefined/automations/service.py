"""Automation runtime: persist graphs, fire time jobs, run event workflows."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from Undefined.automations.address import (
    legacy_target_fields,
    resolve_live_event_address,
    resolve_task_address,
)
from Undefined.automations.constants import (
    DEFAULT_BLANK_LLM_MAX_ITERATIONS,
    DEFAULT_EVENT_COOLDOWN_SECONDS,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_NODES,
    DEFAULT_NODE_TIMEOUT_SECONDS,
    DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
    LOOP_MAX_ITERATIONS,
    SELF_CALL_TOOL_NAME,
)
from Undefined.automations.engine import iter_matching_tasks
from Undefined.automations.logutil import preview_text
from Undefined.automations.match import AutomationEvent
from Undefined.automations.migrate import migrate_legacy_task
from Undefined.automations.runner import (
    WorkflowError,
    WorkflowRunner,
    collect_session_identity,
    find_start_node,
    start_kind,
)
from Undefined.automations.short import build_short_automation
from Undefined.automations.storage import AutomationStorage
from Undefined.automations.triggers import build_apscheduler_trigger
from Undefined.automations.validate import validate_automation
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.utils import io
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.sender import AddressBoundSender
from Undefined.weixin.audio import VOICE_SOURCE_SUFFIXES

logger = logging.getLogger(__name__)

CONTEXT_DIR = Path("data/scheduler_context")

_AI_SERVICE_CONTEXT_ATTRS: tuple[tuple[str, str], ...] = (
    ("cognitive_service", "_cognitive_service"),
    ("knowledge_manager", "_knowledge_manager"),
    ("meme_service", "_meme_service"),
    ("attachment_registry", "attachment_registry"),
)


class AutomationService:
    """Load, persist, match and run automation graphs."""

    def __init__(
        self,
        ai_client: Any,
        sender: Any,
        onebot_client: Any,
        history_manager: Any,
        storage: Any | None = None,
    ) -> None:
        self._apscheduler = AsyncIOScheduler()
        self.ai = ai_client
        self.sender = sender
        self.onebot = onebot_client
        self.history_manager = history_manager
        self.storage = storage or AutomationStorage()

        loaded = self.storage.load_tasks()
        self.tasks: dict[str, Any] = {
            task_id: migrate_legacy_task(info) if isinstance(info, dict) else info
            for task_id, info in loaded.items()
        }
        self._running_ids: set[str] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._run_lock = asyncio.Lock()
        self._run_sema = asyncio.Semaphore(DEFAULT_MAX_CONCURRENT)

        if not self._apscheduler.running:
            self._apscheduler.start()

        time_jobs = self._recover_tasks()
        logger.info(
            "[自动化] 运行时已启动: tasks=%s time_jobs=%s enabled=%s",
            len(self.tasks),
            time_jobs,
            self._automation_settings()["enabled"],
        )

    @property
    def clock_running(self) -> bool:
        return bool(self._apscheduler.running)

    def shutdown(self) -> None:
        if self._apscheduler.running:
            self._apscheduler.shutdown(wait=False)
            logger.info("[自动化] 运行时已停止")
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()

    def next_run_iso(self, task_id: str) -> str | None:
        job = self._apscheduler.get_job(task_id)
        next_run_time = getattr(job, "next_run_time", None) if job is not None else None
        if next_run_time is None:
            return None
        return str(next_run_time.isoformat())

    def _recover_tasks(self) -> int:
        if not self.tasks:
            logger.info("[自动化] 没有需要恢复的任务")
            return 0

        count = 0
        for task_id, info in list(self.tasks.items()):
            if not isinstance(info, dict):
                continue
            try:
                address = resolve_task_address(
                    info.get("address"),
                    info.get("target_id")
                    if isinstance(info.get("target_id"), int)
                    else None,
                    str(info.get("target_type", "group")),
                )
                if address is not None:
                    info["address"] = address.canonical
                    info["target_id"], info["target_type"] = legacy_target_fields(
                        address
                    )
                self._sync_time_job(task_id, info)
                if build_apscheduler_trigger(info) is not None:
                    count += 1
                    logger.info(
                        "[自动化] 已恢复时间任务: id=%s name=%s kind=%s address=%s next=%s",
                        task_id,
                        str(info.get("task_name") or ""),
                        start_kind(info) or "-",
                        str(info.get("address") or ""),
                        self.next_run_iso(task_id) or "-",
                    )
                else:
                    logger.info(
                        "[自动化] 已恢复事件任务: id=%s name=%s kind=%s enabled=%s",
                        task_id,
                        str(info.get("task_name") or ""),
                        start_kind(info) or "-",
                        bool(info.get("enabled", True)),
                    )
            except Exception as exc:
                logger.error("[自动化] 恢复任务 %s 失败: %s", task_id, exc)

        logger.info(
            "[自动化] 恢复完成: tasks=%s time_jobs=%s",
            len(self.tasks),
            count,
        )
        return count

    async def remove_task(self, task_id: str) -> bool:
        existed = task_id in self.tasks
        context_id = None
        if existed:
            context_id = self.tasks[task_id].get("context_id")
        job_removed = False
        try:
            self._apscheduler.remove_job(task_id)
            job_removed = True
        except Exception:
            logger.debug("[自动化] 无时间任务 job: %s", task_id)
        if not existed and not job_removed:
            logger.warning("[自动化] 删除失败，任务不存在: %s", task_id)
            return False
        if existed:
            del self.tasks[task_id]
            await self.storage.save_all(self.tasks)
        if context_id:
            await self._delete_context_snapshot(context_id)
        logger.info("[自动化] 已删除 %s", task_id)
        return True

    def list_tasks(self) -> dict[str, Any]:
        """列出所有任务"""
        return self.tasks

    def _automation_settings(self) -> dict[str, Any]:
        runtime = getattr(self.ai, "runtime_config", None)
        cfg = getattr(runtime, "automations", None)
        return {
            "max_concurrent": int(
                getattr(cfg, "max_concurrent", DEFAULT_MAX_CONCURRENT)
            ),
            "max_nodes": int(getattr(cfg, "max_nodes", DEFAULT_MAX_NODES)),
            "node_timeout_seconds": float(
                getattr(cfg, "node_timeout_seconds", DEFAULT_NODE_TIMEOUT_SECONDS)
            ),
            "workflow_timeout_seconds": float(
                getattr(
                    cfg, "workflow_timeout_seconds", DEFAULT_WORKFLOW_TIMEOUT_SECONDS
                )
            ),
            "blank_llm_max_iterations": int(
                getattr(
                    cfg, "blank_llm_max_iterations", DEFAULT_BLANK_LLM_MAX_ITERATIONS
                )
            ),
            "loop_max_iterations": min(
                LOOP_MAX_ITERATIONS,
                int(getattr(cfg, "loop_max_iterations", LOOP_MAX_ITERATIONS)),
            ),
            "cooldown_seconds": int(
                getattr(cfg, "default_cooldown_seconds", DEFAULT_EVENT_COOLDOWN_SECONDS)
            ),
            "enabled": bool(getattr(cfg, "enabled", True)),
        }

    def _sync_time_job(self, task_id: str, task_info: dict[str, Any]) -> None:
        trigger = build_apscheduler_trigger(task_info)
        existing = self._apscheduler.get_job(task_id)
        if trigger is None:
            if existing is not None:
                try:
                    self._apscheduler.remove_job(task_id)
                except Exception:
                    logger.debug("[自动化] 移除事件任务的时间 job: %s", task_id)
            return
        self._apscheduler.add_job(
            self._on_time_fire,
            trigger=trigger,
            id=task_id,
            args=[task_id],
            replace_existing=True,
        )
        logger.debug(
            "[自动化] 时间 job 已同步: id=%s kind=%s next=%s",
            task_id,
            start_kind(task_info) or "-",
            self.next_run_iso(task_id) or "-",
        )

    async def upsert_automation(self, task_id: str, task: dict[str, Any]) -> bool:
        """Create or replace a full automation graph."""
        payload = build_short_automation(dict(task))
        payload["task_id"] = task_id
        settings = self._automation_settings()
        validate_automation(payload, max_nodes=int(settings["max_nodes"]))
        raw_target = payload.get("target_id")
        address = resolve_task_address(
            payload.get("address"),
            raw_target if isinstance(raw_target, int) else None,
            str(payload.get("target_type") or "group"),
        )
        if address is not None:
            payload["address"] = address.canonical
            payload["target_id"], payload["target_type"] = legacy_target_fields(address)
        created = task_id not in self.tasks
        if created:
            payload["context_id"] = await self._save_context_snapshot()
        else:
            existing = self.tasks[task_id]
            payload.setdefault("context_id", existing.get("context_id"))
            for key in (
                "last_status",
                "last_run_at",
                "last_error",
                "last_node_id",
                "current_executions",
            ):
                if key not in payload and existing.get(key) is not None:
                    payload[key] = existing.get(key)
        self.tasks[task_id] = payload
        self._sync_time_job(task_id, payload)
        await self.storage.save_all(self.tasks)
        nodes = payload.get("nodes")
        logger.info(
            "[自动化] 已%s: id=%s name=%s kind=%s address=%s enabled=%s next=%s nodes=%s",
            "创建" if created else "更新",
            task_id,
            str(payload.get("task_name") or ""),
            start_kind(payload) or "-",
            str(payload.get("address") or ""),
            bool(payload.get("enabled", True)),
            self.next_run_iso(task_id) or "-",
            len(nodes) if isinstance(nodes, list) else 0,
        )
        return True

    async def set_enabled(self, task_id: str, enabled: bool) -> bool:
        task = self.tasks.get(task_id)
        if not isinstance(task, dict):
            return False
        task["enabled"] = bool(enabled)
        await self.storage.save_all(self.tasks)
        logger.info(
            "[自动化] 已%s: id=%s name=%s",
            "启用" if enabled else "停用",
            task_id,
            str(task.get("task_name") or ""),
        )
        return True

    def _spawn_event_run(
        self,
        task_id: str,
        *,
        event: AutomationEvent,
        start_match: Any,
        live_resources: dict[str, Any] | None,
    ) -> None:
        """Run a non-blocking automation in the background and return immediately."""
        snapshot_event = replace(event, extra=dict(event.extra))
        snapshot_resources = dict(live_resources) if live_resources else None
        logger.info(
            "[自动化] 非阻塞后台执行: id=%s kind=%s address=%s",
            task_id,
            snapshot_event.kind,
            snapshot_event.address,
        )

        async def _run() -> None:
            try:
                await self._run_automation(
                    task_id,
                    event=snapshot_event,
                    start_match=start_match,
                    live_resources=snapshot_resources,
                    time_fire=False,
                )
            except Exception:
                logger.exception("[自动化] 非阻塞执行失败: id=%s", task_id)

        task = asyncio.create_task(_run(), name=f"automation:{task_id}")
        self._background_tasks.add(task)

        def _finalize(done_task: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done_task)
            try:
                exc = done_task.exception()
            except asyncio.CancelledError:
                logger.debug("[自动化] 非阻塞任务已取消: id=%s", task_id)
                return
            if exc is not None:
                logger.exception(
                    "[自动化] 非阻塞任务失败: id=%s",
                    task_id,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )

        task.add_done_callback(_finalize)

    async def handle_event(
        self,
        event: AutomationEvent,
        *,
        live_resources: dict[str, Any] | None = None,
    ) -> bool:
        """Match event automations. Return True if the AI loop should stop.

        ``consume_ai_loop=true`` workflows are awaited before returning.
        Non-blocking workflows are spawned in the background so the main AI
        path can continue immediately.
        """
        settings = self._automation_settings()
        if not settings["enabled"]:
            logger.debug(
                "[自动化] 总开关关闭，忽略事件: kind=%s channel=%s address=%s",
                event.kind,
                event.channel,
                event.address,
            )
            return False
        logger.debug(
            "[自动化] 收到事件: kind=%s channel=%s address=%s sender=%s group=%s text_len=%s preview=%s candidates=%s running=%s",
            event.kind,
            event.channel,
            event.address,
            event.sender_id,
            event.group_id,
            len(event.text or ""),
            preview_text(event.text),
            len(self.tasks),
            len(self._running_ids),
        )
        matches = iter_matching_tasks(
            self.tasks,
            event,
            running_ids=self._running_ids,
            default_cooldown=int(settings["cooldown_seconds"]),
        )
        if not matches:
            logger.debug(
                "[自动化] 无匹配: kind=%s channel=%s address=%s",
                event.kind,
                event.channel,
                event.address,
            )
            return False
        logger.info(
            "[自动化] 命中 %s 条: kind=%s channel=%s address=%s ids=%s",
            len(matches),
            event.kind,
            event.channel,
            event.address,
            ",".join(task_id for task_id, _task, _match in matches),
        )
        consumed = False
        blocking: list[tuple[str, Any]] = []
        for task_id, task, start_match in matches:
            consume_ai = bool(task.get("consume_ai_loop", True))
            logger.info(
                "[自动化] 命中执行: id=%s name=%s kind=%s consume_ai=%s pass_len=%s preview=%s",
                task_id,
                str(task.get("task_name") or ""),
                start_kind(task) or "-",
                consume_ai,
                len(start_match.pass_text),
                preview_text(start_match.pass_text),
            )
            if consume_ai:
                blocking.append((task_id, start_match))
                consumed = True
                continue
            self._spawn_event_run(
                task_id,
                event=event,
                start_match=start_match,
                live_resources=live_resources,
            )
        for task_id, start_match in blocking:
            try:
                await self._run_automation(
                    task_id,
                    event=event,
                    start_match=start_match,
                    live_resources=live_resources,
                    time_fire=False,
                )
            except Exception:
                logger.exception("[自动化] 事件执行失败: id=%s", task_id)
        logger.info(
            "[自动化] 事件处理完成: kind=%s channel=%s address=%s consume_ai=%s background=%s",
            event.kind,
            event.channel,
            event.address,
            consumed,
            len(self._background_tasks),
        )
        return consumed

    async def _mark_run(
        self,
        task_id: str,
        *,
        status: str,
        error: str = "",
        node_id: str = "",
    ) -> None:
        task = self.tasks.get(task_id)
        if not isinstance(task, dict):
            return
        task["last_status"] = status
        task["last_run_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        task["last_error"] = error
        task["last_node_id"] = node_id
        if status == "ok":
            task["current_executions"] = int(task.get("current_executions") or 0) + 1
            max_executions = task.get("max_executions")
            logger.info(
                "[自动化] 运行结果: id=%s status=%s executions=%s/%s node=%s",
                task_id,
                status,
                task["current_executions"],
                max_executions if max_executions is not None else "-",
                node_id or "-",
            )
            await self.storage.save_all(self.tasks)
            if max_executions is not None and int(task["current_executions"]) >= int(
                max_executions
            ):
                logger.info(
                    "[自动化] 达到执行上限，将删除: id=%s executions=%s",
                    task_id,
                    task["current_executions"],
                )
                await self.remove_task(task_id)
            return
        logger.warning(
            "[自动化] 运行结果: id=%s status=%s node=%s error=%s",
            task_id,
            status,
            node_id or "-",
            preview_text(error, limit=200),
        )
        await self.storage.save_all(self.tasks)

    async def _run_automation(
        self,
        task_id: str,
        *,
        event: AutomationEvent | None,
        start_match: Any | None,
        live_resources: dict[str, Any] | None,
        time_fire: bool,
    ) -> None:
        task_info = self.tasks.get(task_id)
        if not isinstance(task_info, dict):
            logger.warning(
                "[自动化] 执行时任务已不存在: id=%s time_fire=%s", task_id, time_fire
            )
            return
        settings = self._automation_settings()
        if not settings["enabled"] or task_info.get("enabled") is False:
            logger.debug(
                "[自动化] 跳过停用任务: id=%s enabled=%s global=%s time_fire=%s",
                task_id,
                task_info.get("enabled", True),
                settings["enabled"],
                time_fire,
            )
            return
        async with self._run_lock:
            if task_id in self._running_ids:
                logger.info("[自动化] 已在运行，跳过 %s", task_id)
                return
            self._running_ids.add(task_id)
        settings = self._automation_settings()
        try:
            async with self._run_sema:
                await self._execute_workflow(
                    task_id,
                    event=event,
                    start_match=start_match,
                    live_resources=live_resources,
                    time_fire=time_fire,
                    settings=settings,
                )
        finally:
            self._running_ids.discard(task_id)

    async def _save_context_snapshot(self) -> str | None:
        ctx = RequestContext.current()
        if not ctx:
            return None

        context_id = uuid.uuid4().hex
        snapshot = {
            "request_type": ctx.request_type,
            "group_id": ctx.group_id,
            "user_id": ctx.user_id,
            "sender_id": ctx.sender_id,
            "channel": ctx.get_resource("channel"),
            "address": ctx.get_resource("address"),
            "resource_keys": list(ctx.get_resources().keys()),
        }
        await io.write_json(CONTEXT_DIR / f"{context_id}.json", snapshot, use_lock=True)
        logger.debug(
            "[自动化] 已保存上下文快照: context_id=%s request_type=%s address=%s",
            context_id,
            snapshot.get("request_type"),
            snapshot.get("address"),
        )
        return context_id

    async def _load_context_snapshot(
        self, context_id: str | None
    ) -> dict[str, Any] | None:
        if not context_id:
            return None
        return await io.read_json(CONTEXT_DIR / f"{context_id}.json", use_lock=False)

    async def _delete_context_snapshot(self, context_id: str | None) -> None:
        if not context_id:
            return
        await io.delete_file(CONTEXT_DIR / f"{context_id}.json")

    def _inject_ai_services(self, tool_context: dict[str, Any]) -> None:
        """Fill AI-owned services that tool handlers read from context."""
        for context_key, attr in _AI_SERVICE_CONTEXT_ATTRS:
            if tool_context.get(context_key) is not None:
                continue
            value = getattr(self.ai, attr, None)
            if value is not None:
                tool_context[context_key] = value

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> Any:
        """执行工具（兼容多版本 AIClient 接口）"""
        if tool_name == SELF_CALL_TOOL_NAME:
            return await self._execute_self_call(tool_args, tool_context)

        self._inject_ai_services(tool_context)
        task_id = tool_context.get("scheduled_task_id") or ""
        logger.info(
            "[自动化] 调用工具: id=%s tool=%s arg_keys=%s",
            task_id,
            tool_name,
            ",".join(sorted(str(key) for key in tool_args.keys())) or "-",
        )
        logger.debug(
            "[自动化] 工具参数: id=%s tool=%s args=%s",
            task_id,
            tool_name,
            preview_text(tool_args, limit=300),
        )
        ai_client: Any = self.ai
        tool_manager = getattr(ai_client, "tool_manager", None)
        if tool_manager is not None and hasattr(tool_manager, "execute_tool"):
            logger.debug("[自动化] 使用 ToolManager 执行工具: %s", tool_name)
            return await tool_manager.execute_tool(tool_name, tool_args, tool_context)

        for attr in ("execute_tool", "_execute_tool"):
            method = getattr(ai_client, attr, None)
            if method is not None:
                logger.debug("[自动化] 使用 AIClient.%s 执行工具: %s", attr, tool_name)
                return await method(tool_name, tool_args, tool_context)

        available = [
            name
            for name in ("tool_manager", "execute_tool", "_execute_tool")
            if hasattr(ai_client, name)
        ]
        logger.error(
            "[自动化] 工具执行入口不可用: tool=%s available=%s",
            tool_name,
            ",".join(available) or "none",
        )
        raise AttributeError("AIClient missing tool execution method")

    async def _execute_self_call(
        self,
        tool_args: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> str:
        """执行定时任务中的“调用自己”逻辑。"""
        prompt = str(tool_args.get("prompt", "")).strip()
        if not prompt:
            raise ValueError("self_instruction 不能为空")

        send_message_callback = tool_context.get("send_message_callback")
        get_recent_messages_callback = tool_context.get("get_recent_messages_callback")
        get_image_url_callback = tool_context.get("get_image_url_callback")
        get_forward_msg_callback = tool_context.get("get_forward_msg_callback")
        send_like_callback = tool_context.get("send_like_callback")
        sender = tool_context.get("sender")
        history_manager = tool_context.get("history_manager")
        onebot_client = tool_context.get("onebot_client")
        task_id = tool_context.get("scheduled_task_id")
        task_name = tool_context.get("scheduled_task_name")

        extra_context: dict[str, Any] = {
            "scheduled_self_call": True,
        }
        extra_context.update(collect_session_identity(tool_context))
        if task_id:
            extra_context["scheduled_task_id"] = task_id
        if task_name:
            extra_context["scheduled_task_name"] = task_name

        logger.info(
            "[自动化] 触发自我督办: task_id=%s task_name=%s prompt_len=%s preview=%s",
            task_id,
            task_name or "",
            len(prompt),
            preview_text(prompt),
        )

        result = await self.ai.ask(
            prompt,
            send_message_callback=send_message_callback,
            get_recent_messages_callback=get_recent_messages_callback,
            get_image_url_callback=get_image_url_callback,
            get_forward_msg_callback=get_forward_msg_callback,
            send_like_callback=send_like_callback,
            sender=sender,
            history_manager=history_manager,
            onebot_client=onebot_client,
            scheduler=self,
            extra_context=extra_context,
        )

        result_text = str(result).strip() if isinstance(result, str) else ""
        if result_text and callable(send_message_callback):
            logger.info(
                "[自动化] 自我督办出站: task_id=%s len=%s preview=%s",
                task_id,
                len(result_text),
                preview_text(result_text),
            )
            await send_message_callback(result_text)
        elif not result_text:
            logger.info("[自动化] 自我督办无文本输出: task_id=%s", task_id)

        return "已执行向未来自己的指令"

    async def _on_time_fire(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        name = str(task.get("task_name") or "") if isinstance(task, dict) else ""
        logger.info(
            "[自动化] 时间触发: id=%s name=%s kind=%s next=%s",
            task_id,
            name,
            start_kind(task) if isinstance(task, dict) else "-",
            self.next_run_iso(task_id) or "-",
        )
        await self._run_automation(
            task_id,
            event=None,
            start_match=None,
            live_resources=None,
            time_fire=True,
        )

    async def _execute_workflow(
        self,
        task_id: str,
        *,
        event: AutomationEvent | None,
        start_match: Any | None,
        live_resources: dict[str, Any] | None,
        time_fire: bool,
        settings: dict[str, Any],
    ) -> None:
        raw_task = self.tasks.get(task_id, {})
        if not isinstance(raw_task, dict):
            return
        task_info = migrate_legacy_task(raw_task)
        if event is not None:
            event_user_id = (
                event.user_id if event.user_id is not None else event.sender_id
            )
            delivery_address = resolve_live_event_address(
                address=event.address,
                channel=event.channel,
                group_id=event.group_id,
                user_id=event_user_id,
            )
        else:
            raw_target = task_info.get("target_id")
            stored_target_id: int | None
            try:
                stored_target_id = int(raw_target) if raw_target is not None else None
            except (TypeError, ValueError):
                stored_target_id = None
            delivery_address = resolve_task_address(
                task_info.get("address"),
                stored_target_id,
                str(task_info.get("target_type") or "group"),
            )
        logger.info(
            "[自动化] 开始执行: id=%s name=%s kind=%s time_fire=%s address=%s consume_ai=%s",
            task_id,
            str(task_info.get("task_name") or ""),
            start_kind(task_info) or "-",
            time_fire,
            str(
                (delivery_address.canonical if delivery_address is not None else "")
                or task_info.get("address")
                or ""
            ),
            bool(task_info.get("consume_ai_loop", True)),
        )
        try:
            context_snapshot = await self._load_context_snapshot(
                task_info.get("context_id")
            )
            if event is not None:
                request_type = "group" if event.channel == "group" else "private"
                group_id = event.group_id
                user_id = (
                    event.user_id if event.user_id is not None else event.sender_id
                )
                sender_id = event.sender_id
            elif context_snapshot:
                request_type = context_snapshot.get("request_type") or (
                    delivery_address.target_type
                    if delivery_address is not None
                    else str(task_info.get("target_type") or "group")
                )
                group_id = context_snapshot.get("group_id")
                user_id = context_snapshot.get("user_id")
                sender_id = context_snapshot.get("sender_id")
            else:
                request_type = (
                    delivery_address.target_type
                    if delivery_address is not None
                    else str(task_info.get("target_type") or "group")
                )
                group_id = None
                user_id = None
                sender_id = None

            if delivery_address is not None:
                request_type = delivery_address.target_type
                if request_type == "group":
                    group_id = delivery_address.target_id
                    user_id = user_id if event is not None else None
                else:
                    group_id = group_id if event is not None else None
                    user_id = delivery_address.target_id
            resolved_target_id = (
                delivery_address.target_id
                if delivery_address is not None
                else task_info.get("target_id")
            )
            logger.debug(
                "[自动化] 投递上下文: id=%s request_type=%s group_id=%s user_id=%s sender_id=%s address=%s snapshot=%s",
                task_id,
                request_type,
                group_id,
                user_id,
                sender_id,
                delivery_address.canonical if delivery_address is not None else "",
                bool(context_snapshot),
            )

            async with RequestContext(
                request_type=request_type,
                group_id=group_id,
                user_id=user_id,
                sender_id=sender_id,
            ) as ctx:

                async def send_msg_cb(
                    message: str, reply_to: int | None = None
                ) -> None:
                    target = (
                        delivery_address.canonical
                        if delivery_address is not None
                        else f"{request_type}:{resolved_target_id}"
                    )
                    logger.info(
                        "[自动化] 发送消息: id=%s target=%s len=%s preview=%s",
                        task_id,
                        target,
                        len(message),
                        preview_text(message),
                    )
                    if (
                        delivery_address is not None
                        and delivery_address.channel == "wechat"
                    ):
                        await self.sender.send_address_message(
                            delivery_address,
                            message,
                            reply_to=reply_to,
                        )
                    elif request_type == "group" and resolved_target_id:
                        await self.sender.send_group_message(
                            resolved_target_id, message, reply_to=reply_to
                        )
                    elif request_type == "private" and resolved_target_id:
                        await self.sender.send_private_message(
                            resolved_target_id, message, reply_to=reply_to
                        )
                    else:
                        logger.warning(
                            "[自动化] 消息未发送: id=%s 无投递目标 type=%s",
                            task_id,
                            request_type,
                        )

                async def send_private_cb(
                    uid: int, msg: str, reply_to: int | None = None
                ) -> None:
                    if (
                        delivery_address is not None
                        and delivery_address.channel == "wechat"
                        and delivery_address.target_id == uid
                    ):
                        await self.sender.send_address_message(
                            delivery_address,
                            msg,
                            reply_to=reply_to,
                        )
                    else:
                        await self.sender.send_private_message(
                            uid,
                            msg,
                            reply_to=reply_to,
                        )

                async def send_img_cb(tid: int, mtype: str, path: str) -> None:
                    if not os.path.exists(path):
                        return
                    file_uri = Path(path).resolve().as_uri()
                    ext = os.path.splitext(path)[1].lower()
                    if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
                        msg = f"[CQ:image,file={file_uri}]"
                        media_kind = "image"
                    elif ext in VOICE_SOURCE_SUFFIXES:
                        msg = f"[CQ:record,file={file_uri}]"
                        media_kind = "record"
                    else:
                        return

                    if mtype == "group":
                        await self.sender.send_group_message(
                            tid, msg, auto_history=False
                        )
                    elif (
                        mtype == "private"
                        and delivery_address is not None
                        and delivery_address.channel == "wechat"
                        and delivery_address.target_id == tid
                    ):
                        await self.sender.send_address_file(
                            delivery_address,
                            path,
                            name=Path(path).name,
                            kind=media_kind,
                            auto_history=False,
                        )
                    elif mtype == "private":
                        await self.sender.send_private_message(
                            tid, msg, auto_history=False
                        )
                    logger.info(
                        "[自动化] 发送媒体: id=%s type=%s target=%s kind=%s path=%s",
                        task_id,
                        mtype,
                        tid,
                        media_kind,
                        path,
                    )

                async def get_recent_cb(
                    chat_id: str, msg_type: str, start: int, end: int
                ) -> list[dict[str, Any]]:
                    return await get_recent_messages_prefer_local(
                        chat_id=chat_id,
                        msg_type=msg_type,
                        start=start,
                        end=end,
                        onebot_client=self.onebot,
                        history_manager=self.history_manager,
                        bot_qq=int(getattr(self.ai, "bot_qq", 0)),
                        attachment_registry=getattr(
                            self.ai, "attachment_registry", None
                        ),
                    )

                async def send_like_cb(uid: int, times: int = 1) -> None:
                    await self.onebot.send_like(uid, times)

                ai_client = self.ai
                memory_storage = self.ai.memory_storage
                runtime_config = self.ai.runtime_config
                sender = (
                    AddressBoundSender(self.sender, delivery_address)
                    if delivery_address is not None
                    and delivery_address.channel == "wechat"
                    else self.sender
                )
                channel = (
                    event.channel
                    if event is not None
                    else (
                        delivery_address.channel
                        if delivery_address is not None
                        else str((context_snapshot or {}).get("channel") or "")
                    )
                )
                address = (
                    event.address
                    if event is not None and event.address
                    else (
                        delivery_address.canonical
                        if delivery_address is not None
                        else str((context_snapshot or {}).get("address") or "")
                    )
                )
                history_manager = self.history_manager
                onebot_client = self.onebot
                automations = self
                scheduler = self
                send_message_callback = send_msg_cb
                get_recent_messages_callback = get_recent_cb
                get_image_url_callback = self.onebot.get_image
                get_forward_msg_callback = self.onebot.get_forward_msg
                send_like_callback = send_like_cb
                send_private_message_callback = send_private_cb
                send_image_callback = send_img_cb
                cognitive_service = getattr(self.ai, "_cognitive_service", None)
                knowledge_manager = getattr(self.ai, "_knowledge_manager", None)
                meme_service = getattr(self.ai, "_meme_service", None)
                attachment_registry = getattr(self.ai, "attachment_registry", None)
                resource_vars = dict(globals())
                resource_vars.update(locals())
                resources = collect_context_resources(resource_vars)
                resource_keys = (
                    context_snapshot.get("resource_keys") if context_snapshot else None
                )
                if resource_keys:
                    for key in resource_keys:
                        if key in resources and resources[key] is not None:
                            ctx.set_resource(key, resources[key])
                else:
                    for key, value in resources.items():
                        if value is not None:
                            ctx.set_resource(key, value)
                if live_resources:
                    for key, value in live_resources.items():
                        if value is not None:
                            ctx.set_resource(key, value)
                if channel:
                    ctx.set_resource("channel", channel)
                if address:
                    ctx.set_resource("address", address)
                ctx.set_resource("sender", sender)
                ctx.set_resource("automations", self)
                ctx.set_resource("scheduler", self)

                session_identity: dict[str, Any] = {"request_type": request_type}
                if group_id is not None:
                    session_identity["group_id"] = group_id
                if user_id is not None:
                    session_identity["user_id"] = user_id
                if sender_id is not None:
                    session_identity["sender_id"] = sender_id
                if channel:
                    session_identity["channel"] = channel
                if address:
                    session_identity["address"] = address
                for key, value in session_identity.items():
                    ctx.set_resource(key, value)

                tool_context = ctx.get_resources()
                tool_context.setdefault("agent_histories", {})
                tool_context["automations"] = self
                tool_context["scheduler"] = self
                tool_context["scheduled_task_id"] = task_id
                tool_context["scheduled_task_name"] = task_info.get("task_name", "")
                tool_context.update(session_identity)
                self._inject_ai_services(tool_context)
                for context_key, _attr in _AI_SERVICE_CONTEXT_ATTRS:
                    value = tool_context.get(context_key)
                    if value is not None:
                        ctx.set_resource(context_key, value)

                resolved_event = event
                if resolved_event is None:
                    resolved_event = AutomationEvent(
                        kind="time",
                        channel=str(channel or "group"),
                        address=str(address or ""),
                        group_id=group_id if isinstance(group_id, int) else None,
                        user_id=user_id if isinstance(user_id, int) else None,
                        sender_id=sender_id if isinstance(sender_id, int) else None,
                    )
                match = start_match
                if match is None:
                    start_node = find_start_node(task_info)
                    if start_node is not None:
                        from Undefined.automations.match import match_start_node

                        match = match_start_node(start_node, resolved_event)
                consume = getattr(match, "consume_result", None) if match else None
                pass_text = (
                    str(getattr(match, "pass_text", "") or resolved_event.text)
                    if match
                    else resolved_event.text
                )

                async def ask_main(prompt: str, extra: dict[str, Any]) -> str:
                    extra_context = dict(extra)
                    extra_context["scheduled_self_call"] = True
                    extra_context["scheduled_task_id"] = task_id
                    extra_context["scheduled_task_name"] = task_info.get(
                        "task_name", ""
                    )
                    extra_context.update(session_identity)
                    logger.info(
                        "[自动化] 调用主 AI: id=%s prompt_len=%s preview=%s",
                        task_id,
                        len(prompt),
                        preview_text(prompt),
                    )
                    result = await self.ai.ask(
                        prompt,
                        send_message_callback=send_msg_cb,
                        get_recent_messages_callback=get_recent_cb,
                        get_image_url_callback=self.onebot.get_image,
                        get_forward_msg_callback=self.onebot.get_forward_msg,
                        send_like_callback=send_like_cb,
                        sender=sender,
                        history_manager=self.history_manager,
                        onebot_client=self.onebot,
                        scheduler=self,
                        extra_context=extra_context,
                    )
                    return str(result).strip() if isinstance(result, str) else ""

                def get_tools() -> list[dict[str, Any]]:
                    manager = getattr(self.ai, "tool_manager", None)
                    if manager is not None and hasattr(manager, "get_openai_tools"):
                        return list(manager.get_openai_tools())
                    return []

                submit_llm = getattr(self.ai, "submit_queued_llm_call", None)

                async def _missing_submit(*_a: Any, **_k: Any) -> dict[str, Any]:
                    raise WorkflowError("LLM 提交入口不可用")

                runner = WorkflowRunner(
                    execute_tool=self._execute_tool,
                    ask_main=ask_main,
                    submit_llm=submit_llm if callable(submit_llm) else _missing_submit,
                    send_message=send_msg_cb,
                    get_openai_tools=get_tools,
                    agent_config=getattr(self.ai, "agent_config", None),
                    tool_context=tool_context,
                    node_timeout_seconds=float(settings["node_timeout_seconds"]),
                    workflow_timeout_seconds=float(
                        settings["workflow_timeout_seconds"]
                    ),
                    blank_llm_max_iterations=int(settings["blank_llm_max_iterations"]),
                    loop_max_iterations=int(settings["loop_max_iterations"]),
                )
                start_time = time.perf_counter()
                try:
                    await runner.run(
                        task_info,
                        event=resolved_event,
                        pass_text=pass_text,
                        consume_mentions=tuple(getattr(consume, "mentions", ()) or ()),
                        consume_stripped=str(
                            getattr(consume, "stripped", "") or resolved_event.text
                        ),
                        mentions_all=tuple(getattr(consume, "mentions_all", ()) or ()),
                    )
                except WorkflowError as exc:
                    logger.exception(
                        "[自动化] 节点失败: id=%s node=%s error=%s",
                        task_id,
                        exc.node_id or "-",
                        exc,
                    )
                    await self._mark_run(
                        task_id,
                        status="failed",
                        error=str(exc),
                        node_id=exc.node_id,
                    )
                    return
                duration = time.perf_counter() - start_time
                logger.info(
                    "[自动化] 执行成功: id=%s name=%s elapsed=%.2fs pass_len=%s",
                    task_id,
                    str(task_info.get("task_name") or ""),
                    duration,
                    len(pass_text),
                )
                await self._mark_run(task_id, status="ok")
        except Exception as e:
            logger.exception("[自动化] 执行出错: id=%s error=%s", task_id, e)
            await self._mark_run(task_id, status="failed", error=str(e))
