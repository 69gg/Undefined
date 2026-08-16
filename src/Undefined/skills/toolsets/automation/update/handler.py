from copy import deepcopy
from typing import Any, Dict

from Undefined.skills.toolsets.automation._runtime import get_automation_service


def _apply_start_fields(task: Dict[str, Any], args: Dict[str, Any]) -> None:
    nodes = task.get("nodes")
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict) or str(node.get("id") or "") != "start":
            continue
        for key in (
            "kind",
            "channels",
            "group_ids",
            "user_ids",
            "mentions",
            "text",
            "text_match",
            "pass_text",
            "cron",
            "time",
            "at",
            "clock",
        ):
            if key in args and args[key] is not None:
                node[key] = args[key]


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    task_id = str(args.get("task_id") or "").strip()
    if not task_id:
        return "task_id 不能为空"
    service = get_automation_service(context)
    if not service:
        return "自动化服务未在上下文中提供"
    existing = service.list_tasks().get(task_id)
    if not isinstance(existing, dict):
        return f"找不到自动化 {task_id}"
    payload = deepcopy(existing)
    skip = {"task_id", "patch_nodes", "merge"}
    for key, value in args.items():
        if key in skip or value is None:
            continue
        if key in {
            "kind",
            "channels",
            "group_ids",
            "user_ids",
            "mentions",
            "text",
            "text_match",
            "pass_text",
            "cron",
            "time",
            "at",
            "clock",
        }:
            continue
        payload[key] = value
    _apply_start_fields(payload, args)
    merge = args.get("merge")
    if isinstance(merge, dict):
        payload.update(merge)
    patches = args.get("patch_nodes")
    if isinstance(patches, list) and patches:
        by_id: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for node in payload.get("nodes") or []:
            if isinstance(node, dict) and node.get("id"):
                node_id = str(node["id"])
                by_id[node_id] = dict(node)
                order.append(node_id)
        for patch in patches:
            if not isinstance(patch, dict) or not patch.get("id"):
                continue
            node_id = str(patch["id"])
            current = by_id.get(node_id, {"id": node_id})
            current.update(patch)
            if node_id not in by_id:
                order.append(node_id)
            by_id[node_id] = current
        payload["nodes"] = [by_id[node_id] for node_id in order]
    try:
        await service.upsert_automation(task_id, payload)
    except Exception as exc:
        return f"更新失败: {exc}"
    return f"已更新自动化 {task_id}"
