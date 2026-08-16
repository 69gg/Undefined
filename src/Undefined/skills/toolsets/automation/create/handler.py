import uuid
from typing import Any, Dict

from Undefined.skills.toolsets.automation._runtime import get_automation_service


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    service = get_automation_service(context)
    if not service:
        return "自动化服务未在上下文中提供"
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        name = str(args.get("task_name") or "auto").strip() or "auto"
        slug = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.lower())
        task_id = f"auto_{slug[:24]}_{uuid.uuid4().hex[:4]}"
    if task_id in service.list_tasks():
        return f"自动化 {task_id} 已存在"
    payload = dict(args)
    payload.pop("task_id", None)
    if not payload.get("address"):
        address = str(context.get("address") or "").strip()
        if address:
            payload["address"] = address
    try:
        await service.upsert_automation(task_id, payload)
    except Exception as exc:
        return f"创建失败: {exc}"
    return f"已创建自动化 {task_id}"
