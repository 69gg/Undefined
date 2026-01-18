"""
任务调度器
用于定时执行 AI 工具
"""

import logging
import time
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..scheduled_task_storage import ScheduledTaskStorage

logger = logging.getLogger(__name__)


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

    def add_task(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        cron_expression: str,
        target_id: int | None = None,
        target_type: str = "group",
        task_name: str | None = None,
        max_executions: int | None = None,
    ) -> bool:
        """添加定时任务

        参数:
            task_id: 任务唯一标识（用户指定或自动生成）
            tool_name: 要执行的工具名称
            tool_args: 工具参数
            cron_expression: crontab 表达式 (分 时 日 月 周)
            target_id: 结果发送目标 ID
            target_type: 结果发送目标类型 (group/private)
            task_name: 任务名称（用于标识，可读名称）
            max_executions: 最大执行次数（None 表示无限）

        返回:
            是否添加成功
        """
        try:
            trigger = CronTrigger.from_crontab(cron_expression)

            self.scheduler.add_job(
                self._execute_tool_wrapper,
                trigger=trigger,
                id=task_id,
                args=[task_id, tool_name, tool_args, target_id, target_type],
                replace_existing=True,
            )

            self.tasks[task_id] = {
                "task_id": task_id,
                "tool_name": tool_name,
                "tool_args": tool_args,
                "cron": cron_expression,
                "target_id": target_id,
                "target_type": target_type,
                "task_name": task_name or "",
                "max_executions": max_executions,
                "current_executions": 0,
            }

            # 持久化保存
            self.storage.save_all(self.tasks)

            logger.info(
                f"添加定时任务成功: {task_id} -> {tool_name} ({cron_expression})"
            )
            return True
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}")
            return False

    def update_task(
        self,
        task_id: str,
        cron_expression: str | None = None,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        task_name: str | None = None,
        max_executions: int | None = None,
    ) -> bool:
        """修改定时任务（不支持修改 task_id）

        参数:
            task_id: 要修改的任务 ID
            cron_expression: 新的 crontab 表达式
            tool_name: 新的工具名称
            tool_args: 新的工具参数
            task_name: 新的任务名称
            max_executions: 新的最大执行次数

        返回:
            是否修改成功
        """
        if task_id not in self.tasks:
            logger.warning(f"修改定时任务失败: 任务不存在 {task_id}")
            return False

        try:
            task_info = self.tasks[task_id]

            if cron_expression is not None:
                trigger = CronTrigger.from_crontab(cron_expression)
                self.scheduler.reschedule_job(task_id, trigger=trigger)
                task_info["cron"] = cron_expression

            if tool_name is not None:
                task_info["tool_name"] = tool_name

            if tool_args is not None:
                task_info["tool_args"] = tool_args

            if task_name is not None:
                task_info["task_name"] = task_name

            if max_executions is not None:
                task_info["max_executions"] = max_executions

            # 持久化保存
            self.storage.save_all(self.tasks)

            logger.info(f"修改定时任务成功: {task_id}")
            return True
        except Exception as e:
            logger.error(f"修改定时任务失败: {e}")
            return False

    def remove_task(self, task_id: str) -> bool:
        """移除定时任务"""
        try:
            self.scheduler.remove_job(task_id)
            if task_id in self.tasks:
                del self.tasks[task_id]
                # 持久化保存
                self.storage.save_all(self.tasks)
            logger.info(f"移除定时任务成功: {task_id}")
            return True
        except Exception as e:
            logger.warning(f"移除定时任务失败 (可能不存在): {e}")
            return False

    def list_tasks(self) -> dict[str, Any]:
        """列出所有任务"""
        return self.tasks

    async def _execute_tool_wrapper(
        self,
        task_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        target_id: int | None,
        target_type: str,
    ) -> None:
        """任务执行包装器"""
        logger.info(f"[任务触发] 定时任务开始执行: ID={task_id}, 工具={tool_name}")
        logger.debug(f"[任务详情] 参数={tool_args}, 目标={target_id}({target_type})")

        try:
            context = {
                "scheduler": self,
                "ai_client": self.ai,
                "sender": self.sender,
                "onebot_client": self.onebot,
                "history_manager": self.history_manager,
            }

            start_time = time.perf_counter()
            result = await self.ai._execute_tool(tool_name, tool_args, context)
            duration = time.perf_counter() - start_time

            if result and target_id:
                msg = f"【定时任务执行结果】\n工具: {tool_name}\n结果:\n{result}"
                if target_type == "group":
                    await self.sender.send_group_message(target_id, msg)
                else:
                    await self.sender.send_private_message(target_id, msg)

            logger.info(
                f"[任务完成] 定时任务执行成功: ID={task_id}, 耗时={duration:.2f}s"
            )

            if task_id in self.tasks:
                task_info = self.tasks[task_id]
                task_info["current_executions"] = (
                    task_info.get("current_executions", 0) + 1
                )

                # 持久化保存执行次数
                self.storage.save_all(self.tasks)

                max_executions = task_info.get("max_executions")
                current_executions = task_info.get("current_executions", 0)

                if max_executions is not None and current_executions >= max_executions:
                    self.remove_task(task_id)
                    logger.info(
                        f"定时任务 {task_id} 已达到最大执行次数 {max_executions}，已自动删除"
                    )

        except Exception as e:
            logger.exception(f"定时任务执行出错: {e}")
            if target_id:
                try:
                    err_msg = f"【定时任务执行失败】\n工具: {tool_name}\n错误: {e}"
                    if target_type == "group":
                        await self.sender.send_group_message(target_id, err_msg)
                    else:
                        await self.sender.send_private_message(target_id, err_msg)
                except Exception:
                    pass
