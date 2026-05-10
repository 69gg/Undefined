from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    attachment_registry = context.get("attachment_registry")
    if attachment_registry is None:
        return "附件系统未初始化"

    uid = str(args["uid"]).strip()
    url: str | None = await attachment_registry.get_url_by_uid(uid)
    if url is None:
        return f"未找到 UID {uid} 对应的 URL（可能不存在或无 source_ref）"
    return url
