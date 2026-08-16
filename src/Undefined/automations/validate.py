"""Validate automation graphs before save / run."""

from __future__ import annotations

from typing import Any

from Undefined.automations.constants import (
    BRANCH_ELSE_CASE,
    CHANNELS,
    DEFAULT_MAX_NODES,
    EVENT_KINDS,
    LOOP_MAX_ITERATIONS,
    NODE_TYPES,
    START_KINDS,
    START_NODE_ID,
)


class AutomationValidationError(ValueError):
    """Raised when an automation graph is invalid."""


def _nodes_by_id(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            raise AutomationValidationError("node id is required")
        if node_id in mapping:
            raise AutomationValidationError(f"duplicate node id: {node_id}")
        mapping[node_id] = node
    return mapping


def _body_ids(node: dict[str, Any]) -> set[str]:
    body = node.get("body")
    if not isinstance(body, list):
        return set()
    return {str(item).strip() for item in body if str(item).strip()}


def validate_automation(
    task: dict[str, Any],
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> None:
    """Raise AutomationValidationError if the graph cannot run."""
    nodes_raw = task.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise AutomationValidationError("nodes must be a non-empty array")
    if len(nodes_raw) > max_nodes:
        raise AutomationValidationError(
            f"automations can contain at most {max_nodes} nodes"
        )

    nodes = _nodes_by_id([item for item in nodes_raw if isinstance(item, dict)])
    starts = [
        node
        for node in nodes.values()
        if str(node.get("type") or "") == "start"
        or str(node.get("id") or "") == START_NODE_ID
    ]
    if len(starts) != 1:
        raise AutomationValidationError("exactly one start node is required")
    start = starts[0]
    if str(start.get("id") or "") != START_NODE_ID:
        raise AutomationValidationError("start node id must be 'start'")
    kind = str(start.get("kind") or "").strip()
    if kind not in START_KINDS:
        raise AutomationValidationError("start.kind is invalid")
    if kind in EVENT_KINDS:
        channels = start.get("channels")
        if not isinstance(channels, list) or not channels:
            raise AutomationValidationError("event start requires channels")
        for channel in channels:
            if str(channel) not in CHANNELS:
                raise AutomationValidationError(f"unknown channel: {channel}")
        if kind in {"member_join", "member_leave"} and any(
            str(channel) != "group" for channel in channels
        ):
            raise AutomationValidationError("member events only support group channel")
        if kind == "poke" and any(str(channel) == "wechat" for channel in channels):
            raise AutomationValidationError("poke does not support wechat channel")
    if kind == "cron" and not str(start.get("cron") or task.get("cron") or "").strip():
        raise AutomationValidationError("cron start requires cron expression")
    if kind == "daily" and not str(start.get("time") or "").strip():
        raise AutomationValidationError("daily start requires time")
    if kind == "at" and not str(start.get("at") or "").strip():
        raise AutomationValidationError("at start requires datetime")
    if kind == "interval":
        try:
            seconds = int(start.get("interval_seconds") or 0)
        except (TypeError, ValueError) as exc:
            raise AutomationValidationError(
                "interval_seconds must be a positive integer"
            ) from exc
        if seconds < 1:
            raise AutomationValidationError(
                "interval_seconds must be a positive integer"
            )

    for node in nodes.values():
        node_type = str(node.get("type") or "").strip()
        if node_type not in NODE_TYPES:
            raise AutomationValidationError(f"unknown node type: {node_type}")
        if node_type in {"loop.times", "loop.each"}:
            max_iterations = int(node.get("max_iterations") or LOOP_MAX_ITERATIONS)
            if max_iterations < 1 or max_iterations > LOOP_MAX_ITERATIONS:
                raise AutomationValidationError(
                    f"loop max_iterations must be 1..{LOOP_MAX_ITERATIONS}"
                )
            body = _body_ids(node)
            if str(node.get("id") or "") in body:
                raise AutomationValidationError("loop body cannot include itself")
            for body_id in body:
                if body_id not in nodes:
                    raise AutomationValidationError(
                        f"loop body node not found: {body_id}"
                    )
                if str(nodes[body_id].get("type") or "") == "start":
                    raise AutomationValidationError("loop body cannot include start")
        if node_type == "branch.llm":
            options = node.get("options")
            if not isinstance(options, list) or len(options) < 2:
                raise AutomationValidationError(
                    "branch.llm requires at least two options"
                )
            seen: set[str] = set()
            for option in options:
                if not isinstance(option, dict):
                    raise AutomationValidationError(
                        "branch.llm options must be objects"
                    )
                option_id = str(option.get("id") or "").strip()
                if not option_id or option_id == BRANCH_ELSE_CASE:
                    raise AutomationValidationError("branch.llm option id is invalid")
                if option_id in seen:
                    raise AutomationValidationError(
                        f"duplicate branch option: {option_id}"
                    )
                seen.add(option_id)
        if node_type == "branch.if":
            cases = node.get("cases")
            if not isinstance(cases, list) or not cases:
                raise AutomationValidationError("branch.if requires cases")

    edges_raw = task.get("edges")
    if not isinstance(edges_raw, list):
        raise AutomationValidationError("edges must be an array")
    loop_bodies: dict[str, set[str]] = {
        str(node.get("id") or ""): _body_ids(node)
        for node in nodes.values()
        if str(node.get("type") or "") in {"loop.times", "loop.each"}
    }
    body_owners: dict[str, str] = {}
    for loop_id, body in loop_bodies.items():
        for body_id in body:
            if body_id in body_owners:
                raise AutomationValidationError(
                    f"node {body_id} belongs to multiple loops"
                )
            body_owners[body_id] = loop_id

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for index, edge in enumerate(edges_raw):
        if not isinstance(edge, dict):
            raise AutomationValidationError(f"edges[{index}] must be an object")
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in nodes or target not in nodes:
            raise AutomationValidationError(f"edges[{index}] references unknown node")
        if source == target:
            raise AutomationValidationError("self-loop edges are not allowed")
        source_loop = body_owners.get(source)
        target_loop = body_owners.get(target)
        kind = str(edge.get("kind") or "").strip()
        if kind == "body":
            continue
        if source_loop and target_loop and source_loop == target_loop:
            adjacency[source].append(target)
            continue
        if source_loop or target_loop:
            if kind == "exit" and source in loop_bodies and target_loop is None:
                adjacency[source].append(target)
                continue
            raise AutomationValidationError(
                "edges cannot cross loop body except loop exit"
            )
        adjacency[source].append(target)

    # Cycle detection on the outer graph (loop bodies are separate DAGs).
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise AutomationValidationError("automation graph contains a cycle")
        visiting.add(node_id)
        for nxt in adjacency.get(node_id, []):
            visit(nxt)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)
