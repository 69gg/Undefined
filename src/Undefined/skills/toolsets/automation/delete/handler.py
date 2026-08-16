from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"
    success = await scheduler.remove_task(task_id)
    if success:
        return f"已删除自动化 {task_id}"
    return f"删除失败，可能不存在: {task_id}"
