from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 update_schedule_task 工具
    修改已存在的定时任务
    """
    task_id = args.get("task_id")
    cron_expression = args.get("cron_expression")
    tool_name = args.get("tool_name")
    tool_args = args.get("tool_args")
    task_name = args.get("task_name")
    max_executions = args.get("max_executions")

    if not task_id:
        return "请提供要修改的任务 ID"

    if max_executions is not None:
        try:
            max_executions = int(max_executions)
            if max_executions < 1:
                return "max_executions 必须大于 0"
        except (ValueError, TypeError):
            return "max_executions 必须是有效的整数"

    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"

    success = scheduler.update_task(
        task_id=task_id,
        cron_expression=cron_expression,
        tool_name=tool_name,
        tool_args=tool_args,
        task_name=task_name,
        max_executions=max_executions,
    )

    if success:
        return f"定时任务 '{task_id}' 已成功修改。"
    else:
        return "修改定时任务失败。可能任务不存在。"
