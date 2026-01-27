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
    tools = args.get("tools")
    execution_mode = args.get("execution_mode")
    task_name = args.get("task_name")
    max_executions = args.get("max_executions")

    if not task_id:
        return "请提供要修改的任务 ID"

    # 验证工具参数：单工具模式或多工具模式二选一
    has_single_tool = tool_name is not None
    has_multi_tools = tools is not None and len(tools) > 0

    if has_single_tool and has_multi_tools:
        return "不能同时使用 tool_name 和 tools 参数，请选择其中一种模式"

    # 验证多工具模式参数
    if has_multi_tools:
        if not isinstance(tools, list):
            return "tools 参数必须是数组"
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                return f"tools[{i}] 必须是对象"
            if "tool_name" not in tool:
                return f"tools[{i}] 缺少 tool_name 字段"
            if "tool_args" not in tool:
                return f"tools[{i}] 缺少 tool_args 字段"

    # 验证执行模式
    if execution_mode is not None and execution_mode not in ("serial", "parallel"):
        return "execution_mode 必须是 'serial' 或 'parallel'"

    # 验证 max_executions
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

    success = await scheduler.update_task(
        task_id=task_id,
        cron_expression=cron_expression,
        tool_name=tool_name,
        tool_args=tool_args,
        task_name=task_name,
        max_executions=max_executions,
        tools=tools,
        execution_mode=execution_mode,
    )

    if success:
        return f"定时任务 '{task_id}' 已成功修改。"
    else:
        return "修改定时任务失败。可能任务不存在。"
