from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    fact = args.get("fact", "")
    if not fact:
        return "记忆内容不能为空"

    memory_storage = context.get("memory_storage")

    if memory_storage:
        memory_uuid = await memory_storage.add(fact)
        if memory_uuid:
            return f"已保存记忆: {fact[:50]}... (UUID: {memory_uuid})"
        else:
            return "保存失败"
    else:
        return "记忆存储未初始化"
