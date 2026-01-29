from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    memory_uuid = args.get("uuid", "")
    fact = args.get("fact", "")
    if not memory_uuid or not fact:
        return "UUID 和记忆内容不能为空"

    memory_storage = context.get("memory_storage")

    if memory_storage:
        success = await memory_storage.update(memory_uuid, fact)
        if success:
            return f"已更新记忆 {memory_uuid}: {fact[:50]}..."
        else:
            return f"更新失败，未找到 UUID 为 {memory_uuid} 的记忆"
    else:
        return "记忆存储未初始化"
