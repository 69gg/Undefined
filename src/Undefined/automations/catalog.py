"""Static catalog for WebUI / tool schemas."""

from __future__ import annotations

from typing import Any

from Undefined.automations.constants import (
    CHANNELS,
    LOOP_MAX_ITERATIONS,
    NODE_TYPES,
    PASS_TEXT_MODES,
    START_KINDS,
    TEXT_MATCH_MODES,
)

NODE_TYPE_META: tuple[dict[str, str], ...] = (
    {
        "id": "start",
        "group": "trigger",
        "label": "Start",
        "description": "Event or time trigger. Exactly one per graph.",
    },
    {
        "id": "tool",
        "group": "action",
        "label": "Tool",
        "description": "Call a registered tool or agent name with interpolated args. Output can be stored as a named variable.",
    },
    {
        "id": "template",
        "group": "action",
        "label": "Template",
        "description": "Render text without an LLM.",
    },
    {
        "id": "llm.blank",
        "group": "llm",
        "label": "Blank LLM",
        "description": "Agent model with a whitelist of tools, toolsets, and agents. Output can be stored as a named variable. Optional extract_vars inject tools so the model writes extra {{name}} values.",
    },
    {
        "id": "llm.agent",
        "group": "llm",
        "label": "Agent",
        "description": "Run a registered Agent. Output can be stored as a named variable. Optional extract_vars inject tools so the model writes extra {{name}} values.",
    },
    {
        "id": "llm.main",
        "group": "llm",
        "label": "Main AI",
        "description": "Call the main AIClient.ask() loop. Output can be stored as a named variable. Optional extract_vars inject tools so the model writes extra {{name}} values.",
    },
    {
        "id": "branch.if",
        "group": "branch",
        "label": "If / else",
        "description": "Match cases on text, mentions, or clock; else is required.",
    },
    {
        "id": "branch.llm",
        "group": "branch",
        "label": "LLM branch",
        "description": "Force the model to pick one option via choose_<id>.",
    },
    {
        "id": "loop.times",
        "group": "loop",
        "label": "Repeat",
        "description": "Run body nodes a fixed number of times (hard cap 25).",
    },
    {
        "id": "loop.each",
        "group": "loop",
        "label": "For each",
        "description": "Iterate a JSON array or line list through body nodes.",
    },
)


def _function_entries(schemas: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if not isinstance(schemas, list):
        return entries
    seen: set[str] = set()
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        function = schema.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append(
            {
                "name": name,
                "description": str(function.get("description") or "").strip()[:240],
            }
        )
    return entries


def _palette_from_ai(ai: Any) -> dict[str, Any]:
    tools: list[dict[str, str]] = []
    agents: list[dict[str, str]] = []
    if ai is None:
        return {"tools": tools, "toolsets": [], "agents": agents}
    tool_reg = getattr(ai, "tool_registry", None)
    agent_reg = getattr(ai, "agent_registry", None)
    agent_names: set[str] = set()
    if agent_reg is not None:
        getter = getattr(agent_reg, "get_agents_schema", None)
        if not callable(getter):
            getter = getattr(agent_reg, "get_schema", None)
        if callable(getter):
            agents = _function_entries(getter())
            agent_names = {item["name"] for item in agents}
    if tool_reg is not None:
        getter = getattr(tool_reg, "get_tools_schema", None)
        if not callable(getter):
            getter = getattr(tool_reg, "get_schema", None)
        if callable(getter):
            for entry in _function_entries(getter()):
                if entry["name"] in agent_names:
                    continue
                tools.append(entry)
    toolset_names = sorted(
        {
            name.split(".", 1)[0]
            for name in (item["name"] for item in tools)
            if "." in name
        }
    )
    return {"tools": tools, "toolsets": toolset_names, "agents": agents}


def build_catalog(*, bot_qq: int | None = None, ai: Any = None) -> dict[str, Any]:
    """Return node types, match modes, palette names, and example presets."""
    bot_mention = str(bot_qq) if bot_qq else "*"
    palette = _palette_from_ai(ai)
    return {
        "node_types": sorted(NODE_TYPES),
        "node_type_meta": [dict(item) for item in NODE_TYPE_META],
        "start_kinds": sorted(START_KINDS),
        "channels": sorted(CHANNELS),
        "text_match_modes": sorted(TEXT_MATCH_MODES),
        "pass_text_modes": sorted(PASS_TEXT_MODES),
        "loop_max_iterations": LOOP_MAX_ITERATIONS,
        "tools": palette["tools"],
        "toolsets": palette["toolsets"],
        "agents": palette["agents"],
        "examples": {
            "mentions_only_written": {
                "mentions": ["10001", "*"],
                "note": "Only listed @ tokens are stripped; leftover [@qq] stays in text.",
            },
            "channels": ["group", "private"],
            "branch_llm_options": [
                {"id": "search", "description": "需要上网搜"},
                {"id": "chat", "description": "直接闲聊回复"},
            ],
            "loop_each": {
                "type": "loop.each",
                "source": "{{web}}",
                "body": ["render"],
            },
        },
        "presets": [
            {
                "id": "daily_main",
                "name": "每日主 AI",
                "task": {
                    "task_name": "每日主 AI",
                    "auto_send_final": True,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "daily",
                            "time": "09:00",
                        },
                        {
                            "id": "main",
                            "type": "llm.main",
                            "prompt": "回顾昨日待办，把最重要的三项发给当前会话。",
                            "emit": True,
                        },
                    ],
                    "edges": [{"from": "start", "to": "main"}],
                },
            },
            {
                "id": "mention_keyword_main",
                "name": "群内 @指定 QQ + 关键词 → 主 AI",
                "task": {
                    "task_name": "关键词主 AI",
                    "consume_ai_loop": True,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "message",
                            "channels": ["group"],
                            "mentions": [bot_mention],
                            "text": "总结",
                            "pass_text": "stripped",
                        },
                        {
                            "id": "main",
                            "type": "llm.main",
                            "prompt": "{{trigger.text}}",
                            "emit": True,
                        },
                    ],
                    "edges": [{"from": "start", "to": "main"}],
                },
            },
            {
                "id": "member_join_welcome",
                "name": "入群欢迎",
                "task": {
                    "task_name": "入群欢迎",
                    "consume_ai_loop": True,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "member_join",
                            "channels": ["group"],
                        },
                        {
                            "id": "welcome",
                            "type": "template",
                            "template": "欢迎 {{trigger.nickname}} 入群。",
                            "emit": True,
                        },
                    ],
                    "edges": [{"from": "start", "to": "welcome"}],
                },
            },
            {
                "id": "hotspot_dag",
                "name": "热点 DAG（@ 专项）",
                "task": {
                    "task_name": "热点",
                    "consume_ai_loop": True,
                    "auto_send_final": True,
                    "nodes": [
                        {
                            "id": "start",
                            "type": "start",
                            "kind": "message",
                            "channels": ["group"],
                            "mentions": [bot_mention],
                            "text": "热点",
                            "pass_text": "stripped",
                        },
                        {
                            "id": "web",
                            "type": "llm.agent",
                            "agent": "web_agent",
                            "input": "{{trigger.text}}",
                        },
                        {
                            "id": "render",
                            "type": "tool",
                            "tool_name": "render.render_markdown",
                            "args": {"markdown": "{{web}}"},
                            "emit": True,
                        },
                        {
                            "id": "info",
                            "type": "llm.agent",
                            "agent": "info_agent",
                            "input": "{{web}}",
                        },
                    ],
                    "edges": [
                        {"from": "start", "to": "web"},
                        {"from": "web", "to": "render"},
                        {"from": "web", "to": "info"},
                    ],
                },
            },
        ],
    }
