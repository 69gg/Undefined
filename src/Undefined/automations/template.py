"""``{{path}}`` template interpolation for workflow nodes."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


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
