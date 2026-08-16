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


def build_catalog(*, bot_qq: int | None = None) -> dict[str, Any]:
    """Return node types, match modes, and example presets."""
    bot_mention = str(bot_qq) if bot_qq else "*"
    return {
        "node_types": sorted(NODE_TYPES),
        "start_kinds": sorted(START_KINDS),
        "channels": sorted(CHANNELS),
        "text_match_modes": sorted(TEXT_MATCH_MODES),
        "pass_text_modes": sorted(PASS_TEXT_MODES),
        "loop_max_iterations": LOOP_MAX_ITERATIONS,
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
                            "template": "欢迎 {{trigger.user_id}} 入群。",
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
