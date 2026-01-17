"""
任务调度器
用于定时执行 AI 工具
"""

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度器"""

    def __init__(
        self,
        ai_client: Any,
        sender: Any,
        onebot_client: Any,
        history_manager: Any,
    ) -> None:
        """初始化调度器

        参数:
            ai_client: AI 客户端实例 (AIClient)
            sender: 消息发送器实例 (MessageSender)
            onebot_client: OneBot 客户端实例
            history_manager: 历史记录管理器
        """
        self.scheduler = AsyncIOScheduler()
        self.ai = ai_client
        self.sender = sender
        self.onebot = onebot_client
        self.history_manager = history_manager
        self.tasks: dict[str, Any] = {}

        # 确保 scheduler 在 event loop 中运行
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("任务调度器已启动")

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
                "tool_name": tool_name,
                "tool_args": tool_args,
                "cron": cron_expression,
                "target_id": target_id,
                "target_type": target_type,
                "task_name": task_name or "",
                "max_executions": max_executions,
                "current_executions": 0,
            }

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
        logger.info(f"开始执行定时任务: tool={tool_name}, args={tool_args}")

        try:
            context = {
                "scheduler": self,
                "ai_client": self.ai,
                "sender": self.sender,
                "onebot_client": self.onebot,
                "history_manager": self.history_manager,
            }

            result = await self.ai._execute_tool(tool_name, tool_args, context)

            if result and target_id:
                msg = f"【定时任务执行结果】\n工具: {tool_name}\n结果:\n{result}"
                if target_type == "group":
                    await self.sender.send_group_message(target_id, msg)
                else:
                    await self.sender.send_private_message(target_id, msg)

            logger.info(f"定时任务执行完成: {tool_name}")

            if task_id in self.tasks:
                task_info = self.tasks[task_id]
                task_info["current_executions"] = (
                    task_info.get("current_executions", 0) + 1
                )

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
