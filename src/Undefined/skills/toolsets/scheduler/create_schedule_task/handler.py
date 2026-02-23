from typing import Any, Dict
import uuid
import logging

logger = logging.getLogger(__name__)
SELF_CALL_TOOL_NAME = "scheduler.call_self"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """创建一个新的定时任务，支持 Crontab 表达式"""
    """
    执行 create_schedule_task 工具
    创建一个定时执行的任务
    """
    task_name = args.get("task_name")
    cron_expression = args.get("cron_expression")
    tool_name = args.get("tool_name")
    tool_args = args.get("tool_args", {})
    tools = args.get("tools")
    execution_mode = args.get("execution_mode", "serial")
    max_executions = args.get("max_executions")
    self_instruction = args.get("self_instruction")

    # 验证参数
    if not cron_expression:
        return "cron_expression 参数不能为空"

    # 验证工具参数：单工具模式或多工具模式二选一
    has_single_tool = tool_name is not None
    has_multi_tools = tools is not None and len(tools) > 0
    has_self_instruction = self_instruction is not None

    normalized_self_instruction = ""
    if has_self_instruction:
        normalized_self_instruction = str(self_instruction).strip()
        if not normalized_self_instruction:
            return "self_instruction 不能为空"

    mode_count = sum([has_single_tool, has_multi_tools, has_self_instruction])
    if mode_count == 0:
        return "必须提供 tool_name（单工具模式）、tools（多工具模式）或 self_instruction（调用自己模式）参数"

    if mode_count > 1:
        return "tool_name、tools、self_instruction 不能同时使用，请选择其中一种模式"

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
    if execution_mode not in ("serial", "parallel"):
        return "execution_mode 必须是 'serial' 或 'parallel'"

    # 验证 max_executions
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

    # 优先从 context 获取（避免并发问题）
    if target_id is None:
        target_id = context.get("group_id") or context.get("user_id")
        if context.get("group_id"):
            target_type = "group"
        elif context.get("user_id"):
            target_type = "private"

    if not target_type:
        target_type = "group"

    resolved_tool_name = tool_name
    resolved_tool_args = tool_args
    resolved_tools = tools
    if has_self_instruction:
        resolved_tool_name = SELF_CALL_TOOL_NAME
        resolved_tool_args = {"prompt": normalized_self_instruction}
        resolved_tools = None

    success = await scheduler.add_task(
        task_id=task_id,
        tool_name=resolved_tool_name
        or (resolved_tools[0]["tool_name"] if resolved_tools else ""),
        tool_args=resolved_tool_args
        or (resolved_tools[0]["tool_args"] if resolved_tools else {}),
        cron_expression=cron_expression,
        target_id=target_id,
        target_type=target_type,
        task_name=task_name,
        max_executions=max_executions,
        tools=resolved_tools,
        execution_mode=execution_mode,
        self_instruction=normalized_self_instruction if has_self_instruction else None,
    )

    if success:
        name_info = f" '{task_name}'" if task_name else ""
        max_info = f"，最多执行 {max_executions} 次" if max_executions else ""

        if has_self_instruction:
            return (
                f"定时任务{name_info}已成功添加 (ID: {task_id})。\n"
                f"将在 '{cron_expression}' 时间调用未来的自己，指令：{normalized_self_instruction}{max_info}。"
            )
        if has_multi_tools and tools:
            mode_info = (
                f"，执行模式：{'并行' if execution_mode == 'parallel' else '串行'}"
            )
            tools_list = ", ".join([t["tool_name"] for t in tools])
            return f"定时任务{name_info}已成功添加 (ID: {task_id})。\n将在 '{cron_expression}' 时间执行 {len(tools)} 个工具：{tools_list}{mode_info}{max_info}。"
        else:
            return f"定时任务{name_info}已成功添加 (ID: {task_id})。\n将在 '{cron_expression}' 时间执行工具 '{tool_name}'{max_info}。"
    else:
        return "添加定时任务失败。请检查 crontab 表达式是否正确。"
