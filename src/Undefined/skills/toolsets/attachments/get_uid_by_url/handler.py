from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    attachment_registry = context.get("attachment_registry")
    if attachment_registry is None:
        return "附件系统未初始化"

    url = str(args["url"]).strip()
    uid: str | None = await attachment_registry.get_uid_by_url(url)
    if uid is None:
        return f"未找到 URL {url} 对应的附件 UID"
    return uid
