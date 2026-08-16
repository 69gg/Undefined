"""Migrate legacy cron tasks into start + DAG automations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from Undefined.automations.constants import (
    SELF_CALL_TOOL_NAME,
    START_NODE_ID,
    TIME_KINDS,
)


def _legacy_tools(data: dict[str, Any]) -> list[dict[str, Any]]:
    tools = data.get("tools")
    if isinstance(tools, list) and tools:
        normalized: list[dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("tool_name") or "").strip()
            if not name:
                continue
            args = item.get("tool_args")
            normalized.append(
                {
                    "tool_name": name,
                    "tool_args": args if isinstance(args, dict) else {},
                }
            )
        if normalized:
            return normalized
    tool_name = str(data.get("tool_name") or "").strip()
    if tool_name:
        args = data.get("tool_args")
        return [
            {
                "tool_name": tool_name,
                "tool_args": args if isinstance(args, dict) else {},
            }
        ]
    return []


def _self_instruction(data: dict[str, Any], tools: list[dict[str, Any]]) -> str:
    raw = str(data.get("self_instruction") or "").strip()
    if raw:
        return raw
    if tools and tools[0].get("tool_name") == SELF_CALL_TOOL_NAME:
        args = tools[0].get("tool_args")
        if isinstance(args, dict):
            return str(args.get("prompt") or "").strip()
    if str(data.get("tool_name") or "") == SELF_CALL_TOOL_NAME:
        args = data.get("tool_args")
        if isinstance(args, dict):
            return str(args.get("prompt") or "").strip()
    return ""


def _start_node(task: dict[str, Any]) -> dict[str, Any] | None:
    nodes = task.get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id") or "") == START_NODE_ID:
            return node
    return None


def migrate_legacy_task(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure a task dict has a start node and edges. Idempotent."""
    task = deepcopy(data)
    nodes = task.get("nodes")
    if isinstance(nodes, list) and nodes:
        task.setdefault("enabled", True)
        task.setdefault("consume_ai_loop", True)
        task.setdefault("auto_send_final", True)
        task.setdefault("edges", [])
        if "compat_continue_on_tool_error" not in task:
            start = _start_node(task)
            kind = str((start or {}).get("kind") or "").strip()
            task["compat_continue_on_tool_error"] = (
                kind in TIME_KINDS and task.get("auto_send_final") is False
            )
        return task

    cron = str(task.get("cron") or "").strip()
    start_node: dict[str, Any] = {
        "id": START_NODE_ID,
        "type": "start",
        "kind": "cron",
        "cron": cron,
    }
    tools = _legacy_tools(task)
    instruction = _self_instruction(task, tools)
    new_nodes: list[dict[str, Any]] = [start_node]
    edges: list[dict[str, Any]] = []

    if instruction:
        new_nodes.append(
            {
                "id": "main",
                "type": "llm.main",
                "prompt": instruction,
                "emit": True,
            }
        )
        edges.append({"from": START_NODE_ID, "to": "main"})
    elif len(tools) > 1 and str(task.get("execution_mode") or "serial") == "parallel":
        for index, tool in enumerate(tools):
            node_id = f"tool_{index}"
            new_nodes.append(
                {
                    "id": node_id,
                    "type": "tool",
                    "tool_name": tool["tool_name"],
                    "args": tool["tool_args"],
                }
            )
            edges.append({"from": START_NODE_ID, "to": node_id})
    elif tools:
        previous = START_NODE_ID
        for index, tool in enumerate(tools):
            node_id = f"tool_{index}"
            new_nodes.append(
                {
                    "id": node_id,
                    "type": "tool",
                    "tool_name": tool["tool_name"],
                    "args": tool["tool_args"],
                }
            )
            edges.append({"from": previous, "to": node_id})
            previous = node_id
    else:
        new_nodes.append(
            {
                "id": "main",
                "type": "llm.main",
                "prompt": "",
                "emit": True,
            }
        )
        edges.append({"from": START_NODE_ID, "to": "main"})

    task["nodes"] = new_nodes
    task["edges"] = edges
    task.setdefault("enabled", True)
    task.setdefault("consume_ai_loop", True)
    # 旧定时任务由工具自己出站；自我督办节点带 emit=true。
    task.setdefault("auto_send_final", False)
    task.setdefault("compat_continue_on_tool_error", True)
    return task
