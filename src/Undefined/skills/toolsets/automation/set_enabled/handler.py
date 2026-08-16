from typing import Any, Dict

from Undefined.skills.toolsets.automation._runtime import get_automation_service


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    service = get_automation_service(context)
    if not service:
        return "自动化服务未在上下文中提供"
    enabled = bool(args.get("enabled"))
    success = await service.set_enabled(task_id, enabled)
    if not success:
        return f"找不到自动化 {task_id}"
    return f"自动化 {task_id} 已{'启用' if enabled else '停用'}"
