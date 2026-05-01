from __future__ import annotations

import logging
from typing import Any, Dict

from Undefined.attachments import scope_from_context

logger = logging.getLogger(__name__)

_QQ_AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&nk={user_id}&s={size_code}"

_SIZE_MAP = {
    40: 0,
    100: 1,
    140: 2,
    640: 3,
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取 QQ 用户头像并注册到附件系统，返回图片 UID。"""
    user_id = args.get("user_id")
    size = args.get("size", 100)

    if user_id is None:
        return "请提供 QQ 号（user_id 参数）"

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return "参数类型错误：user_id 必须是整数"

    if user_id <= 0:
        return "QQ 号必须为正整数"

    size_code = _SIZE_MAP.get(size, 1)
    avatar_url = _QQ_AVATAR_URL.format(user_id=user_id, size_code=size_code)

    attachment_registry = context.get("attachment_registry")
    scope_key = scope_from_context(context)
    if attachment_registry is None or not scope_key:
        return "当前会话不支持附件注册"

    try:
        record = await attachment_registry.register_remote_url(
            scope_key,
            avatar_url,
            kind="image",
            display_name=f"avatar_{user_id}.jpg",
            source_kind="get_avatar",
            source_ref=f"qq:{user_id}",
        )
    except Exception as exc:
        logger.exception("get_avatar 注册失败: user_id=%s err=%s", user_id, exc)
        return f"获取头像失败：{exc}"

    return f'<attachment uid="{record.uid}"/>'
