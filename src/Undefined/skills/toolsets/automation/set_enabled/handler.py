from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"
    enabled = bool(args.get("enabled"))
    success = await scheduler.set_enabled(task_id, enabled)
    if not success:
        return f"找不到自动化 {task_id}"
    return f"自动化 {task_id} 已{'启用' if enabled else '停用'}"
