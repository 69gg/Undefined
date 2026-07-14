"""
任务调度器
用于定时执行 AI 工具
"""

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.scheduled_task_storage import ScheduledTaskStorage
from Undefined.utils.message_targets import DeliveryAddress, parse_delivery_address
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.sender import AddressBoundSender
from Undefined.utils import io

logger = logging.getLogger(__name__)

CONTEXT_DIR = Path("data/scheduler_context")
SELF_CALL_TOOL_NAME = "scheduler.call_self"


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

        # 从存储加载任务
        self.tasks: dict[str, Any] = self.storage.load_tasks()

        # 确保 scheduler 在 event loop 中运行
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("[任务调度] 任务调度服务已启动")

        # 恢复已有的任务
        self._recover_tasks()

    def _recover_tasks(self) -> None:
        """从存储中恢复任务并添加到调度器"""
        if not self.tasks:
            logger.info("[任务调度] 没有需要恢复的定时任务")
            return

        count = 0
        for task_id, info in list(self.tasks.items()):
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
                trigger = CronTrigger.from_crontab(info["cron"])
                self.scheduler.add_job(
                    self._execute_tool_wrapper,
                    trigger=trigger,
                    id=task_id,
                    args=[
                        task_id,
                        info["tool_name"],
                        info["tool_args"],
                        info["target_id"],
                        info["target_type"],
                    ],
                    replace_existing=True,
                )
                count += 1
                logger.debug(f"[任务调度] 已恢复任务: {task_id} ({info['tool_name']})")
            except Exception as e:
                logger.error(f"[任务调度错误] 恢复定时任务 {task_id} 失败: {e}")
                # 如果任务恢复失败（如格式错误），保留在 self.tasks 中还是删除？
                # 目前保留，由用户或后续逻辑处理

        if count > 0:
            logger.info(f"成功恢复 {count} 个定时任务")

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
            trigger = CronTrigger.from_crontab(cron_expression)
            address = _resolve_task_address(
                target_address,
                target_id,
                target_type,
            )
            if address is not None:
                target_id, target_type = _legacy_target_fields(address)

            context_id = await self._save_context_snapshot()

            self.scheduler.add_job(
                self._execute_tool_wrapper,
                trigger=trigger,
                id=task_id,
                args=[task_id, tool_name, tool_args, target_id, target_type],
                replace_existing=True,
            )

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

            self.tasks[task_id] = task_data

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
                trigger = CronTrigger.from_crontab(cron_expression)
                self.scheduler.reschedule_job(task_id, trigger=trigger)
                task_info["cron"] = cron_expression

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

            # 持久化保存
            await self.storage.save_all(self.tasks)

            logger.info(f"修改定时任务成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"修改定时任务失败: {e}")
            return False

    async def remove_task(self, task_id: str) -> bool:
        """移除定时任务"""
        try:
            context_id = None
            if task_id in self.tasks:
                context_id = self.tasks[task_id].get("context_id")
            self.scheduler.remove_job(task_id)
            if task_id in self.tasks:
                del self.tasks[task_id]
                await self.storage.save_all(self.tasks)
            if context_id:
                await self._delete_context_snapshot(context_id)
            logger.info(f"移除定时任务成功: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"移除定时任务失败 (可能不存在): {e}")
            return False

    def list_tasks(self) -> dict[str, Any]:
        """列出所有任务"""
        return self.tasks

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
        """任务执行包装器"""
        task_info = self.tasks.get(task_id, {})
        tools = task_info.get("tools")
        execution_mode = task_info.get("execution_mode", "serial")
        delivery_address = _resolve_task_address(
            task_info.get("address"),
            target_id,
            target_type,
        )

        # 兼容旧格式：如果没有 tools 字段，使用单工具模式
        if not tools:
            tools = [{"tool_name": tool_name, "tool_args": tool_args}]

        logger.info(
            f"[任务触发] 定时任务开始执行: ID={task_id}, 工具数={len(tools)}, 模式={execution_mode}"
        )
        logger.debug(
            "[任务详情] 目标=%s",
            delivery_address.canonical if delivery_address is not None else "未指定",
        )

        try:
            context_snapshot = await self._load_context_snapshot(
                task_info.get("context_id")
            )
            if context_snapshot:
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
                    user_id = None
                else:
                    group_id = None
                    user_id = delivery_address.target_id
            else:
                if request_type == "group" and group_id is None:
                    group_id = target_id
                if request_type == "private" and user_id is None:
                    user_id = target_id

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
                    elif request_type == "group" and target_id:
                        await self.sender.send_group_message(
                            target_id, message, reply_to=reply_to
                        )
                    elif request_type == "private" and target_id:
                        await self.sender.send_private_message(
                            target_id, message, reply_to=reply_to
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
                    elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
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
                    delivery_address.channel
                    if delivery_address is not None
                    else str((context_snapshot or {}).get("channel") or "")
                )
                address = (
                    delivery_address.canonical
                    if delivery_address is not None
                    else str((context_snapshot or {}).get("address") or "")
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
                if channel:
                    ctx.set_resource("channel", channel)
                if address:
                    ctx.set_resource("address", address)
                ctx.set_resource("sender", sender)

                start_time = time.perf_counter()
                results = []

                tool_context = ctx.get_resources()
                tool_context.setdefault("agent_histories", {})
                tool_context["scheduled_task_id"] = task_id
                tool_context["scheduled_task_name"] = task_info.get("task_name", "")
                if execution_mode == "parallel":
                    # 并行执行所有工具
                    results = await asyncio.gather(
                        *[
                            self._execute_tool(
                                tool["tool_name"], tool["tool_args"], tool_context
                            )
                            for tool in tools
                        ],
                        return_exceptions=True,
                    )
                else:
                    # 串行执行所有工具
                    for tool in tools:
                        try:
                            result = await self._execute_tool(
                                tool["tool_name"], tool["tool_args"], tool_context
                            )
                            results.append(result)
                        except Exception as e:
                            logger.error(f"工具 {tool['tool_name']} 执行失败: {e}")
                            results.append(str(e))

                duration = time.perf_counter() - start_time

                # 将所有结果合并为一个字符串
                combined_results = []
                for i, (tool, result) in enumerate(zip(tools, results)):
                    if isinstance(result, Exception):
                        combined_results.append(
                            f"工具 {i + 1} ({tool['tool_name']}): 执行失败 - {result}"
                        )
                    elif result:
                        combined_results.append(
                            f"工具 {i + 1} ({tool['tool_name']}): {result}"
                        )
                    else:
                        combined_results.append(
                            f"工具 {i + 1} ({tool['tool_name']}): 执行完成，无返回结果"
                        )

                logger.info(
                    f"[任务完成] 定时任务执行成功: ID={task_id}, 耗时={duration:.2f}s"
                )

                # 更新执行次数
                if task_id in self.tasks:
                    task_info = self.tasks[task_id]
                    task_info["current_executions"] = (
                        task_info.get("current_executions", 0) + 1
                    )

                    # 持久化保存执行次数
                    await self.storage.save_all(self.tasks)

                    max_executions = task_info.get("max_executions")
                    current_executions = task_info.get("current_executions", 0)

                    if (
                        max_executions is not None
                        and current_executions >= max_executions
                    ):
                        await self.remove_task(task_id)
                        logger.info(
                            f"定时任务 {task_id} 已达到最大执行次数 {max_executions}，已自动删除"
                        )

        except Exception as e:
            logger.exception(f"定时任务执行出错: {e}")
