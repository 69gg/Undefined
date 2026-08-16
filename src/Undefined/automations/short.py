"""Build a minimal automation graph from a short-command payload."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from Undefined.automations.constants import EVENT_KINDS, START_NODE_ID, TIME_KINDS
from Undefined.automations.migrate import migrate_legacy_task


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_int_list(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _clock_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("clock")
    if isinstance(raw, dict):
        return dict(raw)
    clock: dict[str, Any] = {}
    if body.get("after"):
        clock["after"] = str(body.get("after"))
    if body.get("before"):
        clock["before"] = str(body.get("before"))
    weekdays = _as_int_list(body.get("weekdays"))
    if weekdays:
        clock["weekdays"] = weekdays
    return clock or None


def build_short_automation(body: dict[str, Any]) -> dict[str, Any]:
    """Turn a compact create/update payload into a start + action graph.

    Full graphs (``nodes`` present) are returned after legacy migration.
    Short commands may specify ``kind`` / ``channels`` / ``mentions`` / ``text``
    plus one of ``prompt`` / ``self_instruction`` / ``tool_name`` / ``agent``.
    """
    if isinstance(body.get("nodes"), list) and body["nodes"]:
        return migrate_legacy_task(deepcopy(body))

    kind = str(body.get("kind") or "").strip()
    cron = str(body.get("cron") or body.get("cron_expression") or "").strip()
    if not kind:
        if cron:
            kind = "cron"
        elif body.get("time"):
            kind = "daily"
        elif body.get("at"):
            kind = "at"
        elif body.get("interval_seconds"):
            kind = "interval"
        else:
            kind = "message"

    start: dict[str, Any] = {"id": START_NODE_ID, "type": "start", "kind": kind}
    if kind in EVENT_KINDS:
        channels = _as_str_list(body.get("channels"))
        if not channels:
            if kind in {"member_join", "member_leave"}:
                channels = ["group"]
            elif kind == "poke":
                channels = ["group", "private"]
            else:
                channels = ["group"]
        start["channels"] = channels
        group_ids = _as_int_list(body.get("group_ids"))
        if group_ids:
            start["group_ids"] = group_ids
        user_ids = _as_int_list(body.get("user_ids"))
        if user_ids:
            start["user_ids"] = user_ids
        mentions = _as_str_list(body.get("mentions"))
        if mentions:
            start["mentions"] = mentions
        text = str(body.get("text") or "").strip()
        if text:
            start["text"] = text
        text_match = str(body.get("text_match") or "").strip()
        if text_match:
            start["text_match"] = text_match
        pass_text = str(body.get("pass_text") or "").strip()
        if pass_text:
            start["pass_text"] = pass_text
    if kind in TIME_KINDS:
        if cron:
            start["cron"] = cron
        if body.get("time"):
            start["time"] = str(body.get("time")).strip()
        if body.get("at"):
            start["at"] = str(body.get("at")).strip()
        if body.get("interval_seconds") is not None:
            start["interval_seconds"] = int(body.get("interval_seconds") or 0)
        weekdays = _as_int_list(body.get("weekdays"))
        if weekdays:
            start["weekdays"] = weekdays
    clock = _clock_from_body(body)
    if clock:
        start["clock"] = clock

    nodes: list[dict[str, Any]] = [start]
    edges: list[dict[str, Any]] = []
    prompt = str(body.get("prompt") or body.get("self_instruction") or "").strip()
    agent = str(body.get("agent") or "").strip()
    tool_name = str(body.get("tool_name") or "").strip()
    if prompt:
        nodes.append(
            {
                "id": "main",
                "type": "llm.main",
                "prompt": prompt,
                "emit": True,
            }
        )
        edges.append({"from": START_NODE_ID, "to": "main"})
    elif agent:
        nodes.append(
            {
                "id": "agent",
                "type": "llm.agent",
                "agent": agent,
                "input": str(body.get("input") or "{{trigger.text}}"),
                "emit": bool(body.get("emit", False)),
            }
        )
        edges.append({"from": START_NODE_ID, "to": "agent"})
    elif tool_name:
        tool_args = body.get("tool_args")
        args = dict(tool_args) if isinstance(tool_args, dict) else {}
        nodes.append(
            {
                "id": "tool_0",
                "type": "tool",
                "tool_name": tool_name,
                "args": args,
                "emit": bool(body.get("emit", False)),
            }
        )
        edges.append({"from": START_NODE_ID, "to": "tool_0"})
    else:
        nodes.append(
            {
                "id": "main",
                "type": "llm.main",
                "prompt": "{{trigger.text}}",
                "emit": True,
            }
        )
        edges.append({"from": START_NODE_ID, "to": "main"})

    payload: dict[str, Any] = {
        "task_name": str(body.get("task_name") or "").strip(),
        "enabled": body.get("enabled", True),
        "consume_ai_loop": body.get("consume_ai_loop", True),
        "auto_send_final": body.get("auto_send_final", True),
        "nodes": nodes,
        "edges": edges,
    }
    if body.get("address"):
        payload["address"] = str(body.get("address")).strip()
    if body.get("target_id") is not None:
        payload["target_id"] = body.get("target_id")
    if body.get("target_type"):
        payload["target_type"] = str(body.get("target_type"))
    if body.get("max_executions") is not None:
        payload["max_executions"] = body.get("max_executions")
    if body.get("cooldown_seconds") is not None:
        payload["cooldown_seconds"] = body.get("cooldown_seconds")
    if cron:
        payload["cron"] = cron
    if prompt:
        payload["self_instruction"] = prompt
    return migrate_legacy_task(payload)


def patch_nodes(task: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge node objects by id into an existing graph."""
    updated = deepcopy(task)
    nodes = updated.get("nodes")
    if not isinstance(nodes, list):
        return updated
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            continue
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
    updated["nodes"] = [by_id[node_id] for node_id in order if node_id in by_id]
    return updated
