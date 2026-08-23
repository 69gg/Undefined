"""LLM node variable extraction via injected tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from Undefined.automations.constants import (
    EXTRACT_TOOL_PREFIX,
    EXTRACT_VAR_NODE_TYPES,
    RESERVED_VARIABLE_NAMES,
)
from Undefined.automations.template import OUTPUT_VAR_PATTERN, is_valid_output_var


@dataclass(frozen=True)
class ExtractVar:
    """One named value the model should emit via a tool call."""

    name: str
    description: str


def parse_extract_vars(node: dict[str, Any]) -> list[ExtractVar]:
    """Return configured extract variables for an LLM node."""
    node_type = str(node.get("type") or "").strip()
    if node_type not in EXTRACT_VAR_NODE_TYPES:
        return []
    raw = node.get("extract_vars")
    if not isinstance(raw, list):
        return []
    items: list[ExtractVar] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or name in seen or not is_valid_output_var(name):
            continue
        seen.add(name)
        items.append(
            ExtractVar(
                name=name,
                description=str(entry.get("description") or "").strip(),
            )
        )
    return items


def extract_tool_name(var_name: str) -> str:
    """OpenAI tool name for an extract variable."""
    return f"{EXTRACT_TOOL_PREFIX}{var_name}"


def extract_var_from_tool_name(tool_name: str) -> str | None:
    """Return the variable name if ``tool_name`` is an extract tool."""
    prefix = EXTRACT_TOOL_PREFIX
    if not tool_name.startswith(prefix):
        return None
    name = tool_name[len(prefix) :].strip()
    return name or None


def build_extract_tools(specs: list[ExtractVar]) -> list[dict[str, Any]]:
    """Build OpenAI tool schemas for extract variables."""
    tools: list[dict[str, Any]] = []
    for spec in specs:
        description = spec.description or f"输出变量 {spec.name}"
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": extract_tool_name(spec.name),
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "description": description,
                            }
                        },
                        "required": ["value"],
                    },
                },
            }
        )
    return tools


def extract_prompt_hint(specs: list[ExtractVar]) -> str:
    """Instruction telling the model to call extract tools."""
    if not specs:
        return ""
    lines = [
        "请调用下列工具输出变量（参数为 value）：",
    ]
    for spec in specs:
        label = spec.description or spec.name
        lines.append(f"- {extract_tool_name(spec.name)}：{label}")
    return "\n".join(lines)


def merge_extract_tools(
    tools: list[dict[str, Any]] | None,
    extra: Any,
) -> list[dict[str, Any]]:
    """Append extract tool schemas, skipping duplicate function names."""
    merged = list(tools or [])
    if not isinstance(extra, list) or not extra:
        return merged
    existing: set[str] = set()
    for schema in merged:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        name = function.get("name") if isinstance(function, dict) else ""
        if name:
            existing.add(str(name))
    for schema in extra:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        name = function.get("name") if isinstance(function, dict) else ""
        if not name or str(name) in existing:
            continue
        merged.append(schema)
        existing.add(str(name))
    return merged


def _value_from_args(var_name: str, function_args: dict[str, Any]) -> str:
    if "value" in function_args and function_args["value"] is not None:
        return str(function_args["value"])
    if var_name in function_args and function_args[var_name] is not None:
        return str(function_args[var_name])
    if len(function_args) == 1:
        only = next(iter(function_args.values()))
        if only is not None:
            return str(only)
    return ""


def apply_extract_tool_call(
    function_name: str,
    function_args: dict[str, Any] | None,
    *,
    sink: dict[str, str],
    names: set[str],
) -> str | None:
    """Handle an extract tool call. Return a tool result, or None if unrelated."""
    var_name = extract_var_from_tool_name(str(function_name or ""))
    if var_name is None or var_name not in names:
        return None
    args = function_args if isinstance(function_args, dict) else {}
    sink[var_name] = _value_from_args(var_name, args)
    return f"已写入变量 {var_name}"


def apply_extract_tool_from_context(
    function_name: str,
    function_args: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> str | None:
    """Context-based extract intercept for main AI / Agent tool execution."""
    if not isinstance(context, dict):
        return None
    sink = context.get("automation_extract_sink")
    raw_names = context.get("automation_extract_names")
    if not isinstance(sink, dict):
        return None
    if isinstance(raw_names, (set, frozenset)):
        names = {str(item) for item in raw_names}
    elif isinstance(raw_names, (list, tuple)):
        names = {str(item) for item in raw_names}
    else:
        return None
    return apply_extract_tool_call(
        function_name,
        function_args,
        sink=sink,
        names=names,
    )


def assign_extracted_vars(
    variables: dict[str, Any],
    sink: dict[str, str],
) -> None:
    """Expose extracted values as ``{{name}}`` / ``{{vars.name}}``."""
    if not sink:
        return
    vars_ns = variables.get("vars")
    if not isinstance(vars_ns, dict):
        vars_ns = {}
        variables["vars"] = vars_ns
    for name, value in sink.items():
        if name in RESERVED_VARIABLE_NAMES:
            continue
        if not OUTPUT_VAR_PATTERN.fullmatch(name):
            continue
        variables[name] = value
        vars_ns[name] = value
