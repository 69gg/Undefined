from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    memory_storage = context.get("memory_storage")

    if memory_storage:
        memories = memory_storage.get_all()
        if not memories:
            return "当前没有任何记忆"

        lines = ["当前记忆列表："]
        for m in memories:
            lines.append(f"- [{m.uuid}] ({m.created_at}): {m.fact}")
        return "\n".join(lines)
    else:
        return "记忆存储未初始化"
