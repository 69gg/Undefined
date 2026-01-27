from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 delete_schedule_task 工具
    删除指定的定时任务
    """
    task_id = args.get("task_id")

    if not task_id:
        "请提供要删除的任务 ID"

    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"

    success = await scheduler.remove_task(task_id)

    if success:
        return f"定时任务 '{task_id}' 已成功删除。"
    else:
        return "删除定时任务失败。可能任务不存在。"
