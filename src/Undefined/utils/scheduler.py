"""
任务调度器
用于定时执行 AI 工具
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from Undefined.automations.constants import (
    DEFAULT_BLANK_LLM_MAX_ITERATIONS,
    DEFAULT_EVENT_COOLDOWN_SECONDS,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_NODES,
    DEFAULT_NODE_TIMEOUT_SECONDS,
    DEFAULT_WORKFLOW_TIMEOUT_SECONDS,
    LOOP_MAX_ITERATIONS,
    SELF_CALL_TOOL_NAME as AUTOMATION_SELF_CALL,
    TIME_KINDS,
)
from Undefined.automations.engine import iter_matching_tasks
from Undefined.automations.match import AutomationEvent
from Undefined.automations.migrate import migrate_legacy_task
from Undefined.automations.runner import (
    WorkflowError,
    WorkflowRunner,
    find_start_node,
    start_kind,
)
from Undefined.automations.triggers import build_apscheduler_trigger
from Undefined.automations.short import build_short_automation
from Undefined.automations.validate import (
    validate_automation,
)
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.utils.message_targets import DeliveryAddress, parse_delivery_address
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.sender import AddressBoundSender
from Undefined.utils import io
from Undefined.weixin.audio import VOICE_SOURCE_SUFFIXES

logger = logging.getLogger(__name__)

CONTEXT_DIR = Path("data/scheduler_context")
SELF_CALL_TOOL_NAME = AUTOMATION_SELF_CALL


def _resolve_task_address(
    address: object,
    target_id: int | None,
    target_type: str,
) -> DeliveryAddress | None:
    address_text = str(address or "").strip()
    explicit_address: DeliveryAddress | None = None
    if address_text:
        explicit_address, error = parse_delivery_address(address_text)
        if error or explicit_address is None:
            raise ValueError(error or "投递地址无效")

    legacy_address: DeliveryAddress | None = None
    if target_id is not None:
        legacy_type = str(target_type or "group").strip().lower()
        if legacy_type not in {"group", "private"}:
            raise ValueError("target_type 只能是 group 或 private")
        channel = "group" if legacy_type == "group" else "qq"
        legacy_address, error = parse_delivery_address(f"{channel}:{target_id}")
        if error or legacy_address is None:
            raise ValueError(error or "投递目标无效")

    if explicit_address is not None:
        if legacy_address is not None and legacy_address != explicit_address:
            raise ValueError("address 与旧目标参数指向不同会话")
        return explicit_address
    return legacy_address


def _legacy_target_fields(address: DeliveryAddress) -> tuple[int | None, str]:
    if address.channel == "wechat":
        return None, "private"
    return address.target_id, address.target_type


class TaskScheduler:
    """任务调度器"""

    def __init__(
        self,
        ai_client: Any,
        sender: Any,
        onebot_client: Any,
        history_manager: Any,
        task_storage: Optional[ScheduledTaskStorage] = None,
    ) -> None:
        """初始化调度器

        参数:
            ai_client: AI 客户端实例 (AIClient)
            sender: 消息发送器实例 (MessageSender)
            onebot_client: OneBot 客户端实例
            history_manager: 历史记录管理器
            task_storage: 任务持久化存储器
        """
        self.scheduler = AsyncIOScheduler()
        self.ai = ai_client
        self.sender = sender
        self.onebot = onebot_client
        self.history_manager = history_manager
        self.storage = task_storage or ScheduledTaskStorage()

        # 从存储加载任务（含旧 scheduled_tasks.json 迁移）
        loaded = self.storage.load_tasks()
        self.tasks: dict[str, Any] = {
            task_id: migrate_legacy_task(info) if isinstance(info, dict) else info
            for task_id, info in loaded.items()
        }
        self._running_ids: set[str] = set()
        self._run_lock = asyncio.Lock()
        self._run_sema = asyncio.Semaphore(DEFAULT_MAX_CONCURRENT)

        # 确保 scheduler 在 event loop 中运行
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("[任务调度] 任务调度服务已启动")

        # 恢复已有的任务
        self._recover_tasks()

    def _recover_tasks(self) -> None:
        """从存储中恢复时间类任务并添加到调度器。"""
        if not self.tasks:
            logger.info("[任务调度] 没有需要恢复的自动化任务")
            return

        count = 0
        for task_id, info in list(self.tasks.items()):
            if not isinstance(info, dict):
                continue
            try:
                address = _resolve_task_address(
                    info.get("address"),
                    info.get("target_id"),
                    str(info.get("target_type", "group")),
                )
                if address is not None:
                    info["address"] = address.canonical
                    info["target_id"], info["target_type"] = _legacy_target_fields(
                        address
                    )
                trigger = build_apscheduler_trigger(info)
                if trigger is None:
                    continue
                self.scheduler.add_job(
                    self._execute_tool_wrapper,
                    trigger=trigger,
                    id=task_id,
                    args=[
                        task_id,
                        info.get("tool_name") or "",
                        info.get("tool_args") or {},
                        info.get("target_id"),
                        str(info.get("target_type") or "group"),
                    ],
                    replace_existing=True,
                )
                count += 1
                logger.debug("[任务调度] 已恢复时间任务: %s", task_id)
            except Exception as e:
                logger.error(f"[任务调度错误] 恢复自动化任务 {task_id} 失败: {e}")

        if count > 0:
            logger.info("成功恢复 %s 个时间类自动化任务", count)

    async def add_task(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        cron_expression: str,
        target_id: int | None = None,
        target_type: str = "group",
        task_name: str | None = None,
        max_executions: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        execution_mode: str = "serial",
        self_instruction: str | None = None,
        target_address: str | None = None,
    ) -> bool:
        """添加定时任务

        参数:
            task_id: 任务唯一标识（用户指定或自动生成）
            tool_name: 要执行的工具名称（单工具模式，向后兼容）
            tool_args: 工具参数（单工具模式，向后兼容）
            cron_expression: crontab 表达式 (分 时 日 月 周)
            target_id: 结果发送目标 ID
            target_type: 结果发送目标类型 (group/private)
            task_name: 任务名称（用于标识，可读名称）
            max_executions: 最大执行次数（None 表示无限）
            tools: 多工具调用列表，格式为 [{"tool_name": "...", "tool_args": {...}}, ...]
            execution_mode: 执行模式，"serial" 串行执行，"parallel" 并行执行
            self_instruction: 面向未来自己的指令文本（可选）

        返回:
            是否添加成功
        """
        try:
            CronTrigger.from_crontab(cron_expression)
            address = _resolve_task_address(
                target_address,
                target_id,
                target_type,
            )
            if address is not None:
                target_id, target_type = _legacy_target_fields(address)

            context_id = await self._save_context_snapshot()

            task_data: dict[str, Any] = {
                "task_id": task_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "cron": cron_expression,
                "target_id": target_id,
                "target_type": target_type,
                "address": address.canonical if address is not None else None,
                "task_name": task_name or "",
                "max_executions": max_executions,
                "current_executions": 0,
                "context_id": context_id,
            }

            resolved_self_instruction = str(self_instruction or "").strip() or None
            if resolved_self_instruction is None and tool_name == SELF_CALL_TOOL_NAME:
                prompt = str(tool_args.get("prompt", "")).strip()
                if prompt:
                    resolved_self_instruction = prompt
            if (
                resolved_self_instruction is None
                and tools
                and len(tools) == 1
                and tools[0].get("tool_name") == SELF_CALL_TOOL_NAME
            ):
                prompt = str(tools[0].get("tool_args", {}).get("prompt", "")).strip()
                if prompt:
                    resolved_self_instruction = prompt
            if resolved_self_instruction is not None:
                task_data["self_instruction"] = resolved_self_instruction

            # 添加多工具支持
            if tools:
                task_data["tools"] = tools
            if execution_mode:
                task_data["execution_mode"] = execution_mode

            task_data = migrate_legacy_task(task_data)
            self.tasks[task_id] = task_data
            self._sync_time_job(task_id, task_data)

            # 持久化保存
            await self.storage.save_all(self.tasks)

            tools_info = f"{len(tools)} 个工具" if tools else f"{tool_name}"
            logger.info(
                f"添加定时任务成功: {task_id} -> {tools_info} ({cron_expression}, {execution_mode})"
            )
            return True
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}")
            return False

    async def update_task(
        self,
        task_id: str,
        cron_expression: str | None = None,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        target_id: int | None = None,
        target_id_provided: bool = False,
        target_type: str | None = None,
        task_name: str | None = None,
        max_executions: int | None = None,
        max_executions_provided: bool = False,
        tools: list[dict[str, Any]] | None = None,
        execution_mode: str | None = None,
        self_instruction: str | None = None,
        target_address: str | None = None,
        target_address_provided: bool = False,
    ) -> bool:
        """修改定时任务（不支持修改 task_id）

        参数:
            task_id: 要修改的任务 ID
            cron_expression: 新的 crontab 表达式
            tool_name: 新的工具名称（单工具模式）
            tool_args: 新的工具参数（单工具模式）
            target_id: 新的发送目标 ID
            target_id_provided: 是否显式更新发送目标 ID（允许清空）
            target_type: 新的发送目标类型
            task_name: 新的任务名称
            max_executions: 新的最大执行次数
            max_executions_provided: 是否显式更新最大执行次数（允许清空）
            tools: 新的多工具调用列表（多工具模式）
            execution_mode: 新的执行模式（"serial" 或 "parallel"）
            self_instruction: 新的面向未来自己的指令文本（可选）

        返回:
            是否修改成功
        """
        if task_id not in self.tasks:
            logger.warning(f"修改定时任务失败: 任务不存在 {task_id}")
            return False

        try:
            task_info = self.tasks[task_id]
            old_context_id = task_info.get("context_id")
            new_context_id = await self._save_context_snapshot()

            if cron_expression is not None:
                task_info["cron"] = cron_expression
                start_node = find_start_node(task_info)
                if start_node is not None:
                    start_node["cron"] = cron_expression
                    if str(start_node.get("kind") or "") in {"", "cron"}:
                        start_node["kind"] = "cron"
                trigger = build_apscheduler_trigger(task_info)
                if trigger is not None:
                    if self.scheduler.get_job(task_id) is not None:
                        self.scheduler.reschedule_job(task_id, trigger=trigger)
                    else:
                        self.scheduler.add_job(
                            self._execute_tool_wrapper,
                            trigger=trigger,
                            id=task_id,
                            args=[
                                task_id,
                                task_info.get("tool_name") or "",
                                task_info.get("tool_args") or {},
                                task_info.get("target_id"),
                                str(task_info.get("target_type") or "group"),
                            ],
                            replace_existing=True,
                        )

            if tool_name is not None:
                task_info["tool_name"] = tool_name
                # 如果修改了 tool_name，清除 tools 字段以避免冲突
                if "tools" in task_info:
                    del task_info["tools"]
                if tool_name != SELF_CALL_TOOL_NAME:
                    task_info.pop("self_instruction", None)

            if tool_args is not None:
                task_info["tool_args"] = tool_args
                if task_info.get("tool_name") == SELF_CALL_TOOL_NAME:
                    prompt = str(tool_args.get("prompt", "")).strip()
                    if prompt:
                        task_info["self_instruction"] = prompt

            if target_address_provided:
                address = _resolve_task_address(
                    target_address,
                    None,
                    "private",
                )
                if address is None:
                    task_info["address"] = None
                    task_info["target_id"] = None
                else:
                    task_info["address"] = address.canonical
                    (
                        task_info["target_id"],
                        task_info["target_type"],
                    ) = _legacy_target_fields(address)
            elif target_id is not None or target_id_provided or target_type is not None:
                if target_id is not None or target_id_provided:
                    task_info["target_id"] = target_id
                if target_type is not None:
                    task_info["target_type"] = target_type
                address = _resolve_task_address(
                    None,
                    task_info.get("target_id"),
                    str(task_info.get("target_type", "group")),
                )
                task_info["address"] = (
                    address.canonical if address is not None else None
                )

            if task_name is not None:
                task_info["task_name"] = task_name

            if max_executions is not None or max_executions_provided:
                task_info["max_executions"] = max_executions

            if tools is not None:
                task_info["tools"] = tools
                # 如果设置了 tools，更新 tool_name 为第一个工具的名称以保持兼容性
                if tools:
                    task_info["tool_name"] = tools[0]["tool_name"]
                    task_info["tool_args"] = tools[0]["tool_args"]
                    if (
                        len(tools) == 1
                        and tools[0].get("tool_name") == SELF_CALL_TOOL_NAME
                    ):
                        prompt = str(
                            tools[0].get("tool_args", {}).get("prompt", "")
                        ).strip()
                        if prompt:
                            task_info["self_instruction"] = prompt
                    else:
                        task_info.pop("self_instruction", None)
                else:
                    task_info.pop("self_instruction", None)

            if execution_mode is not None:
                task_info["execution_mode"] = execution_mode

            if self_instruction is not None:
                prompt = str(self_instruction).strip()
                if prompt:
                    task_info["self_instruction"] = prompt
                    task_info["tool_name"] = SELF_CALL_TOOL_NAME
                    task_info["tool_args"] = {"prompt": prompt}
                    task_info.pop("tools", None)
                    task_info["execution_mode"] = "serial"
                else:
                    task_info.pop("self_instruction", None)

            if (
                tool_name is not None
                or tools is not None
                or self_instruction is not None
            ):
                preserved_nodes = task_info.get("nodes")
                preserved_edges = task_info.get("edges")
                rebuilt = migrate_legacy_task(
                    {**task_info, "nodes": None, "edges": None}
                )
                start_node = find_start_node(task_info)
                rebuilt_start = find_start_node(rebuilt)
                if start_node is not None and rebuilt_start is not None:
                    rebuilt_start.update(
                        {
                            key: value
                            for key, value in start_node.items()
                            if key not in {"id", "type"}
                        }
                    )
                if preserved_nodes and start_kind(task_info) not in TIME_KINDS | {""}:
                    task_info["nodes"] = preserved_nodes
                    task_info["edges"] = preserved_edges
                else:
                    task_info["nodes"] = rebuilt["nodes"]
                    task_info["edges"] = rebuilt["edges"]

            if new_context_id:
                task_info["context_id"] = new_context_id
                if old_context_id and old_context_id != new_context_id:
                    await self._delete_context_snapshot(old_context_id)

            job = self.scheduler.get_job(task_id)
            if job is not None:
                job.modify(
                    args=[
                        task_id,
                        task_info.get("tool_name", ""),
                        task_info.get("tool_args", {}),
                        task_info.get("target_id"),
                        task_info.get("target_type", "group"),
                    ]
                )
            else:
                self._sync_time_job(task_id, task_info)

            # 持久化保存
            await self.storage.save_all(self.tasks)

            logger.info(f"修改定时任务成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"修改定时任务失败: {e}")
            return False

    async def remove_task(self, task_id: str) -> bool:
        """移除定时任务"""
        existed = task_id in self.tasks
        context_id = None
        if existed:
            context_id = self.tasks[task_id].get("context_id")
        job_removed = False
        try:
            self.scheduler.remove_job(task_id)
            job_removed = True
        except Exception:
            logger.debug("[任务调度] 无 APScheduler job: %s", task_id)
        if not existed and not job_removed:
            logger.warning("移除定时任务失败 (可能不存在): %s", task_id)
            return False
        if existed:
            del self.tasks[task_id]
            await self.storage.save_all(self.tasks)
        if context_id:
            await self._delete_context_snapshot(context_id)
        logger.info("移除定时任务成功: %s", task_id)
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
        existing = self.scheduler.get_job(task_id)
        if trigger is None:
            if existing is not None:
                try:
                    self.scheduler.remove_job(task_id)
                except Exception:
                    logger.debug("[任务调度] 移除事件任务的 cron job: %s", task_id)
            return
        self.scheduler.add_job(
            self._execute_tool_wrapper,
            trigger=trigger,
            id=task_id,
            args=[
                task_id,
                task_info.get("tool_name") or "",
                task_info.get("tool_args") or {},
                task_info.get("target_id"),
                str(task_info.get("target_type") or "group"),
            ],
            replace_existing=True,
        )

    async def upsert_automation(self, task_id: str, task: dict[str, Any]) -> bool:
        """Create or replace a full automation graph."""
        payload = build_short_automation(dict(task))
        payload["task_id"] = task_id
        settings = self._automation_settings()
        validate_automation(payload, max_nodes=int(settings["max_nodes"]))
        if task_id not in self.tasks:
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
        return True

    async def set_enabled(self, task_id: str, enabled: bool) -> bool:
        task = self.tasks.get(task_id)
        if not isinstance(task, dict):
            return False
        task["enabled"] = bool(enabled)
        await self.storage.save_all(self.tasks)
        return True

    async def handle_event(
        self,
        event: AutomationEvent,
        *,
        live_resources: dict[str, Any] | None = None,
    ) -> bool:
        """Match and await event automations. Return True if AI loop should stop."""
        settings = self._automation_settings()
        if not settings["enabled"]:
            return False
        matches = iter_matching_tasks(
            self.tasks,
            event,
            running_ids=self._running_ids,
            default_cooldown=int(settings["cooldown_seconds"]),
        )
        if not matches:
            return False
        consumed = False
        for task_id, _task, start_match in matches:
            try:
                await self._run_automation(
                    task_id,
                    event=event,
                    start_match=start_match,
                    live_resources=live_resources,
                    time_fire=False,
                )
                task = self.tasks.get(task_id)
                if isinstance(task, dict) and bool(task.get("consume_ai_loop", True)):
                    consumed = True
            except Exception:
                logger.exception("[自动化] 事件执行失败: %s", task_id)
                task = self.tasks.get(task_id)
                if isinstance(task, dict) and bool(task.get("consume_ai_loop", True)):
                    consumed = True
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
            await self.storage.save_all(self.tasks)
            if max_executions is not None and int(task["current_executions"]) >= int(
                max_executions
            ):
                await self.remove_task(task_id)
                return
        await self.storage.save_all(self.tasks)

    async def _run_automation(
        self,
        task_id: str,
        *,
        event: AutomationEvent | None,
        start_match: Any | None,
        live_resources: dict[str, Any] | None,
        time_fire: bool,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        target_id: int | None = None,
        target_type: str = "group",
    ) -> None:
        task_info = self.tasks.get(task_id)
        if not isinstance(task_info, dict):
            return
        settings = self._automation_settings()
        if not settings["enabled"] or task_info.get("enabled") is False:
            return
        async with self._run_lock:
            if task_id in self._running_ids:
                logger.debug("[自动化] 已在运行，跳过 %s", task_id)
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
                    tool_name=tool_name,
                    tool_args=tool_args or {},
                    target_id=target_id,
                    target_type=target_type,
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

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_context: dict[str, Any],
    ) -> Any:
        """执行工具（兼容多版本 AIClient 接口）"""
        if tool_name == SELF_CALL_TOOL_NAME:
            return await self._execute_self_call(tool_args, tool_context)

        ai_client: Any = self.ai
        tool_manager = getattr(ai_client, "tool_manager", None)
        if tool_manager is not None and hasattr(tool_manager, "execute_tool"):
            logger.debug("[任务调度] 使用 ToolManager 执行工具: %s", tool_name)
            return await tool_manager.execute_tool(tool_name, tool_args, tool_context)

        for attr in ("execute_tool", "_execute_tool"):
            method = getattr(ai_client, attr, None)
            if method is not None:
                logger.debug(
                    "[任务调度] 使用 AIClient.%s 执行工具: %s", attr, tool_name
                )
                return await method(tool_name, tool_args, tool_context)

        available = [
            name
            for name in ("tool_manager", "execute_tool", "_execute_tool")
            if hasattr(ai_client, name)
        ]
        logger.error(
            "[任务调度] 工具执行入口不可用: tool=%s available=%s",
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
        if task_id:
            extra_context["scheduled_task_id"] = task_id
        if task_name:
            extra_context["scheduled_task_name"] = task_name

        logger.info(
            "[任务调度] 触发调用自己: task_id=%s task_name=%s prompt_len=%s",
            task_id,
            task_name or "",
            len(prompt),
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
            await send_message_callback(result_text)

        return "已执行向未来自己的指令"

    async def _execute_tool_wrapper(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        target_id: int | None,
        target_type: str,
    ) -> None:
        """APScheduler 入口：按时间触发运行工作流。"""
        await self._run_automation(
            task_id,
            event=None,
            start_match=None,
            live_resources=None,
            time_fire=True,
            tool_name=tool_name,
            tool_args=tool_args,
            target_id=target_id,
            target_type=target_type,
        )

    async def _execute_workflow(
        self,
        task_id: str,
        *,
        event: AutomationEvent | None,
        start_match: Any | None,
        live_resources: dict[str, Any] | None,
        time_fire: bool,
        tool_name: str,
        tool_args: dict[str, Any],
        target_id: int | None,
        target_type: str,
        settings: dict[str, Any],
    ) -> None:
        _ = tool_name, tool_args
        raw_task = self.tasks.get(task_id, {})
        if not isinstance(raw_task, dict):
            return
        task_info = migrate_legacy_task(raw_task)
        delivery_address = _resolve_task_address(
            (event.address if event is not None and event.address else None)
            or task_info.get("address"),
            event.group_id
            if event is not None and event.channel == "group"
            else (
                event.user_id
                if event is not None
                else task_info.get("target_id") or target_id
            ),
            "group"
            if (event is not None and event.channel == "group")
            else str(task_info.get("target_type") or target_type or "group"),
        )
        logger.info("[任务触发] 自动化开始执行: ID=%s time_fire=%s", task_id, time_fire)
        try:
            context_snapshot = await self._load_context_snapshot(
                task_info.get("context_id")
            )
            if event is not None:
                request_type = "group" if event.channel == "group" else "private"
                group_id = event.group_id
                user_id = event.user_id
                sender_id = event.sender_id
            elif context_snapshot:
                request_type = context_snapshot.get("request_type") or (
                    delivery_address.target_type
                    if delivery_address is not None
                    else ("group" if target_type == "group" else "private")
                )
                group_id = context_snapshot.get("group_id")
                user_id = context_snapshot.get("user_id")
                sender_id = context_snapshot.get("sender_id")
            else:
                request_type = (
                    delivery_address.target_type
                    if delivery_address is not None
                    else ("group" if target_type == "group" else "private")
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
                else target_id
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
                scheduler = self
                send_message_callback = send_msg_cb
                get_recent_messages_callback = get_recent_cb
                get_image_url_callback = self.onebot.get_image
                get_forward_msg_callback = self.onebot.get_forward_msg
                send_like_callback = send_like_cb
                send_private_message_callback = send_private_cb
                send_image_callback = send_img_cb
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

                tool_context = ctx.get_resources()
                tool_context.setdefault("agent_histories", {})
                tool_context["scheduled_task_id"] = task_id
                tool_context["scheduled_task_name"] = task_info.get("task_name", "")

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
                    logger.exception("[自动化] 节点失败: %s %s", task_id, exc)
                    await self._mark_run(
                        task_id,
                        status="failed",
                        error=str(exc),
                        node_id=exc.node_id,
                    )
                    return
                duration = time.perf_counter() - start_time
                logger.info(
                    "[任务完成] 自动化执行成功: ID=%s, 耗时=%.2fs",
                    task_id,
                    duration,
                )
                await self._mark_run(task_id, status="ok")
        except Exception as e:
            logger.exception("自动化执行出错: %s", e)
            await self._mark_run(task_id, status="failed", error=str(e))
