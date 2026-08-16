from typing import Any, Dict


def _start_of(task: Dict[str, Any]) -> Dict[str, Any]:
    for node in task.get("nodes") or []:
        if isinstance(node, dict) and str(node.get("id") or "") == "start":
            return node
    return {}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    _ = args
    scheduler = context.get("scheduler")
    if not scheduler:
        return "调度器未在上下文中提供"
    tasks = scheduler.list_tasks()
    if not tasks:
        return "当前没有自动化"
    lines = ["自动化列表：\n"]
    for task_id, info in tasks.items():
        if not isinstance(info, dict):
            continue
        start = _start_of(info)
        kind = str(start.get("kind") or info.get("cron") or "")
        channels = start.get("channels") or []
        enabled = "开" if info.get("enabled", True) else "关"
        last = str(info.get("last_status") or "-")
        name = str(info.get("task_name") or "")
        lines.append(f"- ID: {task_id}")
        lines.append(f"  名称: {name or '(未命名)'}")
        lines.append(f"  启用: {enabled}  kind: {kind}  场景: {channels}")
        lines.append(f"  上次: {last} {info.get('last_run_at') or ''}")
        if info.get("last_error"):
            lines.append(f"  错误: {info.get('last_error')}")
        lines.append("")
    return "\n".join(lines)
