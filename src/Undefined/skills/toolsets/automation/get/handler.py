import json
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"
    task = scheduler.list_tasks().get(task_id)
    if not isinstance(task, dict):
        return f"找不到自动化 {task_id}"
    payload = dict(task)
    payload["task_id"] = task_id
    return json.dumps(payload, ensure_ascii=False, indent=2)
