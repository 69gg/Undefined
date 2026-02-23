from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)
SELF_CALL_TOOL_NAME = "scheduler.call_self"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 list_schedule_tasks 工具
    列出所有定时任务
    """
    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"

    tasks = scheduler.list_tasks()

    if not tasks:
        return "当前没有定时任务"

    lines = ["定时任务列表：\n"]
    for task_id, info in tasks.items():
        task_name = info.get("task_name", "")
        tool_name = info.get("tool_name", "")
        cron = info.get("cron", "")
        tool_args = info.get("tool_args", {})
        self_instruction = str(
            info.get("self_instruction")
            or (tool_args.get("prompt") if isinstance(tool_args, dict) else "")
        ).strip()
        max_exec = info.get("max_executions")
        current_exec = info.get("current_executions", 0)

        exec_info = ""
        if max_exec is not None:
            exec_info = f" ({current_exec}/{max_exec})"
        else:
            exec_info = f" ({current_exec}次)"

        name_display = f"【{task_name}】" if task_name else ""
        args_str = str(tool_args) if tool_args else "{}"
        tool_display = tool_name
        if tool_name == SELF_CALL_TOOL_NAME:
            tool_display = "scheduler.call_self (调用未来的自己)"
            if self_instruction:
                args_str = f"{{'prompt': '{self_instruction}'}}"

        lines.append(f"- ID: {task_id}")
        lines.append(f"  名称: {name_display}")
        lines.append(f"  工具: {tool_display}")
        lines.append(f"  表达式: {cron}")
        lines.append(f"  参数: {args_str}")
        lines.append(f"  已执行: {exec_info}")
        lines.append("")

    return "\n".join(lines)
