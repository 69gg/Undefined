from __future__ import annotations

import logging
from typing import Any, Dict

from Undefined.attachments import scope_from_context

logger = logging.getLogger(__name__)

_IMAGE_MIME_PREFIX = "image/"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """从 URL 获取图片并注册到附件系统，返回图片 UID。"""
    url = str(args.get("url", "") or "").strip()
    display_name = str(args.get("display_name", "") or "").strip() or None

    if not url:
        return "URL 不能为空"
    if not url.startswith(("http://", "https://")):
        return "URL 必须是 http 或 https 链接"

    attachment_registry = context.get("attachment_registry")
    scope_key = scope_from_context(context)
    if attachment_registry is None or not scope_key:
        return "当前会话不支持附件注册"

    try:
        record = await attachment_registry.register_remote_url(
            scope_key,
            url,
            kind="image",
            display_name=display_name,
            source_kind="fetch_image_uid",
            source_ref=url,
        )
    except Exception as exc:
        logger.exception("fetch_image_uid 注册失败: %s", exc)
        return f"获取图片失败：{exc}"

    # 验证是否为图片类型
    mime = str(getattr(record, "mime_type", "") or "").strip().lower()
    if mime and not mime.startswith(_IMAGE_MIME_PREFIX):
        return f"URL 内容不是图片类型（检测到 {mime}），仅支持图片"

    return f'<pic uid="{record.uid}"/>'
