"""Validate automation graphs before save / run."""

from __future__ import annotations

from typing import Any

from Undefined.automations.constants import (
    BRANCH_ELSE_CASE,
    CHANNELS,
    DEFAULT_MAX_NODES,
    EVENT_KINDS,
    EXTRACT_VAR_NODE_TYPES,
    LOOP_MAX_ITERATIONS,
    NODE_TYPES,
    RESERVED_VARIABLE_NAMES,
    START_KINDS,
    START_NODE_ID,
    STORE_OUTPUT_NODE_TYPES,
)
from Undefined.automations.extract import parse_extract_vars
from Undefined.automations.template import OUTPUT_VAR_PATTERN, output_var_name
from Undefined.automations.triggers import (
    parse_at_datetime,
    parse_cron_expression,
    parse_daily_time,
)


class AutomationValidationError(ValueError):
    """Raised when an automation graph is invalid."""


def _issue(path: str, message: str) -> dict[str, str]:
    return {"path": path, "message": message}


def _body_ids(node: dict[str, Any]) -> set[str]:
    body = node.get("body")
    if not isinstance(body, list):
        return set()
    return {str(item).strip() for item in body if str(item).strip()}


def _required_text(
    node: dict[str, Any],
    key: str,
    *,
    path: str,
    issues: list[dict[str, str]],
) -> None:
    if not str(node.get(key) or "").strip():
        issues.append(_issue(path, f"{key} is required"))


def _index_nodes(
    nodes_raw: list[Any],
    issues: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(nodes_raw):
        if not isinstance(item, dict):
            issues.append(_issue(f"nodes[{index}]", "node must be an object"))
            continue
        node_id = str(item.get("id") or "").strip()
        if not node_id:
            issues.append(_issue(f"nodes[{index}]", "node id is required"))
            continue
        if node_id in mapping:
            issues.append(_issue(f"nodes.{node_id}", f"duplicate node id: {node_id}"))
            continue
        mapping[node_id] = item
    return mapping


def collect_automation_issues(
    task: dict[str, Any],
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> list[dict[str, str]]:
    """Return every graph problem the editor can highlight."""
    issues: list[dict[str, str]] = []
    nodes_raw = task.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        return [_issue("nodes", "nodes must be a non-empty array")]
    if len(nodes_raw) > max_nodes:
        issues.append(
            _issue("nodes", f"automations can contain at most {max_nodes} nodes")
        )

    nodes = _index_nodes(nodes_raw, issues)
    starts = [
        node
        for node in nodes.values()
        if str(node.get("type") or "") == "start"
        or str(node.get("id") or "") == START_NODE_ID
    ]
    if len(starts) != 1:
        issues.append(_issue("start", "exactly one start node is required"))
        start: dict[str, Any] | None = starts[0] if starts else None
    else:
        start = starts[0]
        if str(start.get("id") or "") != START_NODE_ID:
            issues.append(_issue("start", "start node id must be 'start'"))
    if start is not None:
        kind = str(start.get("kind") or "").strip()
        if kind not in START_KINDS:
            issues.append(_issue("start.kind", "start.kind is invalid"))
        elif kind in EVENT_KINDS:
            channels = start.get("channels")
            if not isinstance(channels, list) or not channels:
                issues.append(_issue("start.channels", "event start requires channels"))
            else:
                for channel in channels:
                    if str(channel) not in CHANNELS:
                        issues.append(
                            _issue("start.channels", f"unknown channel: {channel}")
                        )
                if kind in {"member_join", "member_leave"} and any(
                    str(channel) != "group" for channel in channels
                ):
                    issues.append(
                        _issue(
                            "start.channels",
                            "member events only support group channel",
                        )
                    )
                if kind == "poke" and any(
                    str(channel) == "wechat" for channel in channels
                ):
                    issues.append(
                        _issue("start.channels", "poke does not support wechat channel")
                    )
        if kind == "cron":
            cron = str(start.get("cron") or task.get("cron") or "").strip()
            if not cron:
                issues.append(
                    _issue("start.cron", "cron start requires cron expression")
                )
            else:
                try:
                    parse_cron_expression(cron)
                except (TypeError, ValueError) as exc:
                    issues.append(_issue("start.cron", str(exc)))
        if kind == "daily":
            daily_time = str(start.get("time") or "").strip()
            if not daily_time:
                issues.append(_issue("start.time", "daily start requires time"))
            else:
                try:
                    parse_daily_time(daily_time)
                except (TypeError, ValueError) as exc:
                    issues.append(_issue("start.time", str(exc)))
        if kind == "at":
            at = str(start.get("at") or "").strip()
            if not at:
                issues.append(_issue("start.at", "at start requires datetime"))
            else:
                try:
                    parse_at_datetime(at)
                except (TypeError, ValueError) as exc:
                    issues.append(_issue("start.at", str(exc)))
        if kind == "interval":
            try:
                seconds = int(start.get("interval_seconds") or 0)
            except (TypeError, ValueError):
                seconds = 0
                issues.append(
                    _issue(
                        "start.interval_seconds",
                        "interval_seconds must be a positive integer",
                    )
                )
            else:
                if seconds < 1:
                    issues.append(
                        _issue(
                            "start.interval_seconds",
                            "interval_seconds must be a positive integer",
                        )
                    )

    branch_cases: dict[str, set[str]] = {}
    branch_types: dict[str, str] = {}
    for node_id, node in nodes.items():
        node_type = str(node.get("type") or "").strip()
        prefix = f"nodes.{node_id}"
        if node_type not in NODE_TYPES:
            issues.append(_issue(f"{prefix}.type", f"unknown node type: {node_type}"))
            continue
        if node_type == "tool":
            _required_text(
                node,
                "tool_name",
                path=f"{prefix}.tool_name",
                issues=issues,
            )
        elif node_type == "llm.agent":
            _required_text(
                node,
                "agent",
                path=f"{prefix}.agent",
                issues=issues,
            )
            prompt = node.get("input") or node.get("prompt")
            if not str(prompt or "").strip():
                issues.append(_issue(f"{prefix}.input", "llm.agent input is required"))
        elif node_type == "llm.main":
            _required_text(
                node,
                "prompt",
                path=f"{prefix}.prompt",
                issues=issues,
            )
        elif node_type == "llm.blank" and not any(
            str(node.get(key) or "").strip() for key in ("system_prompt", "user_prompt")
        ):
            issues.append(
                _issue(
                    f"{prefix}.user_prompt",
                    "llm.blank requires a system_prompt or user_prompt",
                )
            )
        if node_type in {"loop.times", "loop.each"}:
            try:
                max_iterations = int(node.get("max_iterations") or LOOP_MAX_ITERATIONS)
            except (TypeError, ValueError):
                max_iterations = 0
            if max_iterations < 1 or max_iterations > LOOP_MAX_ITERATIONS:
                issues.append(
                    _issue(
                        f"{prefix}.max_iterations",
                        f"loop max_iterations must be 1..{LOOP_MAX_ITERATIONS}",
                    )
                )
            body = _body_ids(node)
            if node_id in body:
                issues.append(
                    _issue(f"{prefix}.body", "loop body cannot include itself")
                )
            for body_id in body:
                if body_id not in nodes:
                    issues.append(
                        _issue(f"{prefix}.body", f"loop body node not found: {body_id}")
                    )
                elif str(nodes[body_id].get("type") or "") == "start":
                    issues.append(
                        _issue(f"{prefix}.body", "loop body cannot include start")
                    )
        if node_type == "branch.llm":
            branch_types[node_id] = node_type
            _required_text(
                node,
                "input",
                path=f"{prefix}.input",
                issues=issues,
            )
            options = node.get("options")
            option_ids: set[str] = set()
            if not isinstance(options, list) or len(options) < 2:
                issues.append(
                    _issue(
                        f"{prefix}.options", "branch.llm requires at least two options"
                    )
                )
            else:
                seen: set[str] = set()
                for option_index, option in enumerate(options):
                    if not isinstance(option, dict):
                        issues.append(
                            _issue(
                                f"{prefix}.options[{option_index}]",
                                "branch.llm options must be objects",
                            )
                        )
                        continue
                    option_id = str(option.get("id") or "").strip()
                    if not option_id or option_id == BRANCH_ELSE_CASE:
                        issues.append(
                            _issue(
                                f"{prefix}.options[{option_index}]",
                                "branch.llm option id is invalid",
                            )
                        )
                        continue
                    if option_id in seen:
                        issues.append(
                            _issue(
                                f"{prefix}.options",
                                f"duplicate branch option: {option_id}",
                            )
                        )
                    seen.add(option_id)
                    option_ids.add(option_id)
            branch_cases[node_id] = option_ids
        if node_type == "branch.if":
            branch_types[node_id] = node_type
            cases = node.get("cases")
            case_ids: set[str] = set()
            if not isinstance(cases, list) or not cases:
                issues.append(_issue(f"{prefix}.cases", "branch.if requires cases"))
            else:
                seen_cases: set[str] = set()
                for case_index, case in enumerate(cases):
                    case_path = f"{prefix}.cases[{case_index}]"
                    if not isinstance(case, dict):
                        issues.append(
                            _issue(case_path, "branch.if cases must be objects")
                        )
                        continue
                    case_id = str(case.get("id") or "").strip()
                    if not case_id or case_id == BRANCH_ELSE_CASE:
                        issues.append(_issue(case_path, "branch.if case id is invalid"))
                        continue
                    if case_id in seen_cases:
                        issues.append(
                            _issue(
                                f"{prefix}.cases",
                                f"duplicate branch case: {case_id}",
                            )
                        )
                    seen_cases.add(case_id)
                    case_ids.add(case_id)
            branch_cases[node_id] = case_ids
        if node_type in STORE_OUTPUT_NODE_TYPES:
            custom = output_var_name(node)
            if custom:
                if not OUTPUT_VAR_PATTERN.fullmatch(custom):
                    issues.append(
                        _issue(
                            f"{prefix}.output_var",
                            "output_var must start with a letter or underscore",
                        )
                    )
                elif custom in RESERVED_VARIABLE_NAMES:
                    issues.append(
                        _issue(
                            f"{prefix}.output_var",
                            f"output_var '{custom}' is reserved",
                        )
                    )
        if node_type in EXTRACT_VAR_NODE_TYPES:
            raw_extract = node.get("extract_vars")
            if raw_extract is not None and not isinstance(raw_extract, list):
                issues.append(
                    _issue(f"{prefix}.extract_vars", "extract_vars must be an array")
                )
            else:
                seen_extract: set[str] = set()
                for extract_index, entry in enumerate(
                    raw_extract if isinstance(raw_extract, list) else []
                ):
                    extract_path = f"{prefix}.extract_vars[{extract_index}]"
                    if not isinstance(entry, dict):
                        issues.append(
                            _issue(extract_path, "extract_vars entries must be objects")
                        )
                        continue
                    extract_name = str(entry.get("name") or "").strip()
                    if not extract_name:
                        issues.append(
                            _issue(extract_path, "extract variable name is required")
                        )
                        continue
                    if not OUTPUT_VAR_PATTERN.fullmatch(extract_name):
                        issues.append(
                            _issue(
                                extract_path,
                                "extract variable name must start with a letter or underscore",
                            )
                        )
                        continue
                    if extract_name in RESERVED_VARIABLE_NAMES:
                        issues.append(
                            _issue(
                                extract_path,
                                f"extract variable '{extract_name}' is reserved",
                            )
                        )
                        continue
                    if extract_name in seen_extract:
                        issues.append(
                            _issue(
                                f"{prefix}.extract_vars",
                                f"duplicate extract variable: {extract_name}",
                            )
                        )
                        continue
                    seen_extract.add(extract_name)

    claimed: dict[str, str] = {node_id: node_id for node_id in nodes}
    for node_id, node in nodes.items():
        if str(node.get("type") or "") not in STORE_OUTPUT_NODE_TYPES:
            continue
        if not bool(node.get("store_output", True)):
            continue
        custom = output_var_name(node)
        if not custom or custom == node_id:
            continue
        owner = claimed.get(custom)
        if owner and owner != node_id:
            issues.append(
                _issue(
                    f"nodes.{node_id}.output_var",
                    f"variable '{custom}' already used by node {owner}",
                )
            )
            continue
        claimed[custom] = node_id

    for node_id, node in nodes.items():
        if str(node.get("type") or "") not in EXTRACT_VAR_NODE_TYPES:
            continue
        for spec in parse_extract_vars(node):
            owner = claimed.get(spec.name)
            if owner:
                issues.append(
                    _issue(
                        f"nodes.{node_id}.extract_vars",
                        f"variable '{spec.name}' already used by node {owner}",
                    )
                )
                continue
            claimed[spec.name] = node_id

    edges_raw = task.get("edges")
    if not isinstance(edges_raw, list):
        issues.append(_issue("edges", "edges must be an array"))
        return issues

    loop_bodies: dict[str, set[str]] = {
        str(node.get("id") or ""): _body_ids(node)
        for node in nodes.values()
        if str(node.get("type") or "") in {"loop.times", "loop.each"}
    }
    body_owners: dict[str, str] = {}
    for loop_id, body in loop_bodies.items():
        for body_id in body:
            if body_id in body_owners:
                issues.append(
                    _issue(
                        f"nodes.{body_id}",
                        f"node {body_id} belongs to multiple loops",
                    )
                )
                continue
            body_owners[body_id] = loop_id

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    branch_outgoing: dict[str, list[tuple[str, str]]] = {
        node_id: [] for node_id in branch_types
    }
    for index, edge in enumerate(edges_raw):
        path = f"edges[{index}]"
        if not isinstance(edge, dict):
            issues.append(_issue(path, f"edges[{index}] must be an object"))
            continue
        source = str(edge.get("from") or "").strip()
        target = str(edge.get("to") or "").strip()
        if source not in nodes or target not in nodes:
            issues.append(_issue(path, f"edges[{index}] references unknown node"))
            continue
        if source == target:
            issues.append(_issue(path, "self-loop edges are not allowed"))
            continue
        source_loop = body_owners.get(source)
        target_loop = body_owners.get(target)
        kind = str(edge.get("kind") or "").strip()
        if kind == "body":
            continue
        edge_is_valid = False
        if source_loop and target_loop and source_loop == target_loop:
            adjacency[source].append(target)
            edge_is_valid = True
        elif source_loop or target_loop:
            if kind == "exit" and source in loop_bodies and target_loop is None:
                adjacency[source].append(target)
                edge_is_valid = True
            else:
                issues.append(
                    _issue(path, "edges cannot cross loop body except loop exit")
                )
        else:
            adjacency[source].append(target)
            edge_is_valid = True
        if edge_is_valid and source in branch_outgoing:
            branch_outgoing[source].append((str(edge.get("case") or "").strip(), path))

    for node_id, node_type in branch_types.items():
        declared = branch_cases.get(node_id, set())
        outgoing = branch_outgoing.get(node_id, [])
        labels = {label for label, _path in outgoing if label}
        allowed = set(declared)
        if node_type == "branch.if":
            allowed.add(BRANCH_ELSE_CASE)
        for label, edge_path in outgoing:
            if not label:
                issues.append(_issue(edge_path, "branch edge case is required"))
            elif label not in allowed:
                issues.append(_issue(edge_path, f"unknown branch case: {label}"))
        required = set(declared)
        if node_type == "branch.if":
            required.add(BRANCH_ELSE_CASE)
        for missing in sorted(required - labels):
            issues.append(
                _issue(
                    f"nodes.{node_id}",
                    f"branch case requires an outgoing edge: {missing}",
                )
            )

    reachability: dict[str, list[str]] = {
        node_id: list(targets) for node_id, targets in adjacency.items()
    }
    for loop_id, body in loop_bodies.items():
        reachability[loop_id].extend(body_id for body_id in body if body_id in nodes)
    reachable: set[str] = set()
    pending = [START_NODE_ID] if START_NODE_ID in nodes else []
    while pending:
        node_id = pending.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        pending.extend(reachability.get(node_id, []))
    if START_NODE_ID in nodes:
        for node_id in sorted(set(nodes) - reachable):
            issues.append(
                _issue(f"nodes.{node_id}", "node is not reachable from start")
            )

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_reported = False

    def visit(node_id: str) -> None:
        nonlocal cycle_reported
        if node_id in visited or cycle_reported:
            return
        if node_id in visiting:
            issues.append(_issue("edges", "automation graph contains a cycle"))
            cycle_reported = True
            return
        visiting.add(node_id)
        for nxt in adjacency.get(node_id, []):
            visit(nxt)
            if cycle_reported:
                break
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in nodes:
        visit(node_id)
        if cycle_reported:
            break
    return issues


def validate_automation(
    task: dict[str, Any],
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> None:
    """Raise AutomationValidationError if the graph cannot run."""
    issues = collect_automation_issues(task, max_nodes=max_nodes)
    if issues:
        raise AutomationValidationError(issues[0]["message"])
