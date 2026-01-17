"""
任务调度器
用于定时执行 AI 工具
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class TaskScheduler:
    """任务调度器"""

    def __init__(self, ai_client: Any, message_handler: Any) -> None:
        """初始化调度器

        Args:
            ai_client: AI 客户端实例 (AIClient)
            message_handler: 消息处理器实例 (MessageHandler)
        """
        self.scheduler = AsyncIOScheduler()
        self.ai = ai_client
        self.message_handler = message_handler
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
    ) -> bool:
        """添加定时任务

        Args:
            task_id: 任务唯一标识（用户指定或自动生成）
            tool_name: 要执行的工具名称
            tool_args: 工具参数
            cron_expression: crontab 表达式 (分 时 日 月 周)
            target_id: 结果发送目标 ID
            target_type: 结果发送目标类型 (group/private)

        Returns:
            是否添加成功
        """
        try:
            # 解析 crontab
            # 注意：apscheduler 的 CronTrigger 参数顺序是: year, month, day, week, day_of_week, hour, minute, second
            # 标准 crontab 是: minute hour day month day_of_week
            # 这里我们使用 from_crontab 方法
            trigger = CronTrigger.from_crontab(cron_expression)

            self.scheduler.add_job(
                self._execute_tool_wrapper,
                trigger=trigger,
                id=task_id,
                args=[tool_name, tool_args, target_id, target_type],
                replace_existing=True,
            )
            
            self.tasks[task_id] = {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "cron": cron_expression,
                "target_id": target_id,
                "target_type": target_type
            }
            
            logger.info(f"添加定时任务成功: {task_id} -> {tool_name} ({cron_expression})")
            return True
        except Exception as e:
            logger.error(f"添加定时任务失败: {e}")
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
        tool_name: str,
        tool_args: dict[str, Any],
        target_id: int | None,
        target_type: str,
    ) -> None:
        """任务执行包装器"""
        logger.info(f"开始执行定时任务: tool={tool_name}, args={tool_args}")
        
        try:
            # 构造上下文 (模拟 ai.ask 中的 context)
            # 注意：定时任务中很多回调可能需要特殊处理，因为没有实时的用户触发
            
            context = {
                "scheduler": self,
                "ai_client": self.ai,
                # 添加 sender 以便工具可以使用发送功能 (如果工具做了适配)
                "sender": self.message_handler.sender,
                "onebot_client": self.message_handler.onebot,
                # 某些工具可能需要 history_manager
                "history_manager": self.message_handler.history_manager,
            }
            
            # 使用 ai_client 的方法来执行工具 (可以直接复用 _execute_tool)
            # 但是 _execute_tool 是内部方法，也许最好公开或者直接调用 registry
            
            result = await self.ai._execute_tool(tool_name, tool_args, context)
            
            # 如果有结果且指定了发送目标，则发送结果
            if result and target_id:
                msg = f"【定时任务执行结果】\n工具: {tool_name}\n结果:\n{result}"
                if target_type == "group":
                    await self.message_handler.sender.send_group_message(target_id, msg)
                else:
                    await self.message_handler.sender.send_private_message(target_id, msg)
                    
            logger.info(f"定时任务执行完成: {tool_name}")
            
        except Exception as e:
            logger.exception(f"定时任务执行出错: {e}")
            if target_id:
                try:
                    err_msg = f"【定时任务执行失败】\n工具: {tool_name}\n错误: {e}"
                    if target_type == "group":
                        await self.message_handler.sender.send_group_message(target_id, err_msg)
                    else:
                        await self.message_handler.sender.send_private_message(target_id, err_msg)
                except Exception:
                    pass
