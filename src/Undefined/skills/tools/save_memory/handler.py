from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    fact = args.get("fact", "")
    if not fact:
        return "记忆内容不能为空"

    memory_storage = context.get("memory_storage")

    if memory_storage:
        success = memory_storage.add(fact)
        if success:
            return f"已保存记忆: {fact[:50]}..."
        else:
            return "保存失败（可能已存在相同记忆）"
    else:
        return "记忆存储未初始化"
