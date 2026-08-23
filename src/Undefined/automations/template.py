"""``{{path}}`` template interpolation for workflow nodes."""

from __future__ import annotations

import logging
import re
from typing import Any

from Undefined.automations.constants import (
    RESERVED_VARIABLE_NAMES,
    STORE_OUTPUT_NODE_TYPES,
)

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
OUTPUT_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def output_var_name(node: dict[str, Any]) -> str:
    """Return the configured alias, or an empty string when unset."""
    return str(node.get("output_var") or "").strip()


def should_store_output(node: dict[str, Any]) -> bool:
    """Whether this node's text output is exposed as a template variable."""
    node_type = str(node.get("type") or "").strip()
    if node_type not in STORE_OUTPUT_NODE_TYPES:
        return True
    return bool(node.get("store_output", True))


def assign_node_output(
    variables: dict[str, Any],
    node: dict[str, Any],
    output: str,
) -> None:
    """Write a finished node's output into the interpolation context."""
    if not should_store_output(node):
        return
    node_id = str(node.get("id") or "").strip()
    if node_id:
        nodes_vars = variables.setdefault("nodes", {})
        if isinstance(nodes_vars, dict):
            nodes_vars[node_id] = {"output": output}
        variables[node_id] = output
    custom = output_var_name(node)
    if not custom or custom == node_id:
        return
    variables[custom] = output
    vars_ns = variables.setdefault("vars", {})
    if isinstance(vars_ns, dict):
        vars_ns[custom] = output


def is_valid_output_var(name: str) -> bool:
    """True when ``name`` is a legal, non-reserved variable identifier."""
    value = name.strip()
    return (
        bool(OUTPUT_VAR_PATTERN.fullmatch(value))
        and value not in RESERVED_VARIABLE_NAMES
    )


def _lookup(path: str, variables: dict[str, Any]) -> Any:
    current: Any = variables
    for part in path.split("."):
        key = part.strip()
        if not key:
            return None
        if isinstance(current, dict):
            if key in current:
                current = current[key]
                continue
            # Allow {{web}} as shorthand for nodes.web.output
            nodes = current.get("nodes")
            if isinstance(nodes, dict) and key in nodes:
                node_value = nodes[key]
                if isinstance(node_value, dict) and "output" in node_value:
                    current = node_value["output"]
                else:
                    current = node_value
                continue
            return None
        return None
    return current


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Replace ``{{path}}`` placeholders. Unresolved placeholders stay as-is."""

    def replace(match: re.Match[str]) -> str:
        path = str(match.group(1) or "").strip()
        value = _lookup(path, variables)
        if value is None:
            logger.debug("[自动化] 未解析占位符: %s", path)
            return match.group(0)
        if isinstance(value, (dict, list)):
            return str(value)
        return str(value)

    return _PLACEHOLDER_RE.sub(replace, template)


def render_value(value: Any, variables: dict[str, Any]) -> Any:
    """Recursively interpolate strings inside JSON-compatible values."""
    if isinstance(value, str):
        return render_template(value, variables)
    if isinstance(value, list):
        return [render_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {str(key): render_value(item, variables) for key, item in value.items()}
    return value
