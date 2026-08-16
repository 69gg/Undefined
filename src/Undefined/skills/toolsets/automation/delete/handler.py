from typing import Any, Dict

from Undefined.skills.toolsets.automation._runtime import get_automation_service


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    service = get_automation_service(context)
    if not service:
        return "自动化服务未在上下文中提供"
    success = await service.remove_task(task_id)
    if success:
        return f"已删除自动化 {task_id}"
    return f"删除失败，可能不存在: {task_id}"
