from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    memory_uuid = args.get("uuid", "")
    if not memory_uuid:
        return "UUID 不能为空"

    memory_storage = context.get("memory_storage")

    if memory_storage:
        success = await memory_storage.delete(memory_uuid)
        if success:
            return f"已删除记忆 {memory_uuid}"
        else:
            return f"删除失败，未找到 UUID 为 {memory_uuid} 的记忆"
    else:
        return "记忆存储未初始化"
