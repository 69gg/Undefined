from __future__ import annotations
from typing import Any
import json


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"
    kbs = km.list_knowledge_bases()
    return json.dumps(kbs, ensure_ascii=False)
