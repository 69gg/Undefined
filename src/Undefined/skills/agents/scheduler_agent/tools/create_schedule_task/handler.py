from typing import Any, Dict
import uuid
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 create_schedule_task 工具
    创建一个定时执行的任务
    """
    task_name = args.get("task_name")
    cron_expression = args.get("cron_expression")
    tool_name = args.get("tool_name")
    tool_args = args.get("tool_args", {})
    max_executions = args.get("max_executions")

    if max_executions is not None:
        try:
            max_executions = int(max_executions)
            if max_executions < 1:
                return "max_executions 必须大于 0"
        except (ValueError, TypeError):
            return "max_executions 必须是有效的整数"

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    if task_name:
        task_id = f"task_{task_name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:4]}"

    target_type = None
    target_id = None

    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"

    ai_client = context.get("ai_client")
    if target_id is None and ai_client:
        if ai_client.current_group_id:
            target_id = ai_client.current_group_id
            if not target_type:
                target_type = "group"
        elif ai_client.current_user_id:
            target_id = ai_client.current_user_id
            if not target_type:
                target_type = "private"

    if not target_type:
        target_type = "group"

    success = scheduler.add_task(
        task_id=task_id,
        tool_name=tool_name,
        tool_args=tool_args,
        cron_expression=cron_expression,
        target_id=target_id,
        target_type=target_type,
        task_name=task_name,
        max_executions=max_executions,
    )

    if success:
        name_info = f" '{task_name}'" if task_name else ""
        max_info = f"，最多执行 {max_executions} 次" if max_executions else ""
        return f"定时任务{name_info}已成功添加 (ID: {task_id})。\n将在 '{cron_expression}' 时间执行工具 '{tool_name}'{max_info}。"
    else:
        return "添加定时任务失败。请检查 crontab 表达式是否正确。"
