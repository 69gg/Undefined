"""Historian LLM 工具定义。"""

from __future__ import annotations

_REWRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_rewrite",
        "description": "提交绝对化改写后的事件文本",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "改写后的纯文本"},
            },
            "required": ["text"],
        },
    },
}
_READ_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_profile",
        "description": "读取指定实体的当前侧写内容",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["user", "group"],
                    "description": "实体类型：user 或 group",
                },
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID（用户 QQ 号或群号）",
                },
            },
            "required": ["entity_type", "entity_id"],
        },
    },
}
_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_profile",
        "description": "更新用户/群侧写。调用前必须先用 read_profile 查看当前内容",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["user", "group"],
                    "description": "实体类型：user 或 group",
                },
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID（用户 QQ 号或群号）",
                },
                "skip": {
                    "type": "boolean",
                    "description": "是否跳过更新；当新信息不稳定/不足时为 true",
                },
                "skip_reason": {
                    "type": "string",
                    "description": "跳过原因",
                },
                "name": {"type": "string", "description": "用户/群名称"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "身份级标签（角色/核心领域），不写话题",
                },
                "summary": {"type": "string", "description": "侧写正文（Markdown）"},
            },
            "required": ["entity_type", "entity_id", "skip", "name", "tags", "summary"],
        },
    },
}
