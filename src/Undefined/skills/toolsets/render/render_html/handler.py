from __future__ import annotations

from typing import Any, Dict
import logging
import uuid

from Undefined.attachments import scope_from_context

logger = logging.getLogger(__name__)


def _resolve_send_target(
    target_id: Any,
    message_type: Any,
    context: Dict[str, Any],
) -> tuple[int | str | None, str | None, str | None]:
    """从参数或 context 推断发送目标。"""
    if target_id is not None and message_type is not None:
        return target_id, message_type, None
    request_type = str(context.get("request_type", "") or "").strip().lower()
    if request_type == "group":
        gid = context.get("group_id")
        if gid is not None:
            return gid, "group", None
    if request_type == "private":
        uid = context.get("user_id")
        if uid is not None:
            return uid, "private", None
    return None, None, "渲染成功，但缺少发送目标参数"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """将 HTML 内容渲染为图片"""
    html_content = args.get("html_content", "")
    delivery = str(args.get("delivery", "embed") or "embed").strip().lower()
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    if not html_content:
        return "HTML 内容不能为空"
    if delivery not in {"embed", "send"}:
        return f"delivery 无效：{delivery}。仅支持 embed 或 send"

    if delivery == "send" and message_type and message_type not in ("group", "private"):
        return "消息类型必须是 group 或 private"

    try:
        from Undefined.utils.cache import cleanup_cache_dir
        from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

        filename = f"render_{uuid.uuid4().hex[:16]}.png"
        filepath = ensure_dir(RENDER_CACHE_DIR) / filename

        render_html_to_image = context.get("render_html_to_image")
        if not render_html_to_image:
            return "错误：渲染函数 (render_html_to_image) 未在上下文中提供，请检查 AIClient 配置。"

        await render_html_to_image(html_content, str(filepath))

        # 注册到附件系统
        attachment_registry = context.get("attachment_registry")
        scope_key = scope_from_context(context)
        record: Any = None
        if attachment_registry is not None and scope_key:
            try:
                record = await attachment_registry.register_local_file(
                    scope_key,
                    filepath,
                    kind="image",
                    display_name=filename,
                    source_kind="rendered_image",
                    source_ref="render_html",
                )
            except Exception as exc:
                logger.warning("注册渲染图片到附件系统失败: %s", exc)

        if delivery == "embed":
            cleanup_cache_dir(RENDER_CACHE_DIR)
            if record is None:
                return "渲染成功，但无法注册到附件系统（缺少 attachment_registry 或 scope_key）"
            return f'<pic uid="{record.uid}"/>'

        # delivery == "send"
        resolved_target_id, resolved_message_type, target_error = _resolve_send_target(
            target_id, message_type, context
        )
        if target_error or resolved_target_id is None or resolved_message_type is None:
            return target_error or "渲染成功，但缺少发送目标参数"

        send_image_callback = context.get("send_image_callback")
        if send_image_callback:
            await send_image_callback(
                resolved_target_id, resolved_message_type, str(filepath)
            )
            cleanup_cache_dir(RENDER_CACHE_DIR)
            return (
                f"HTML 图片已渲染并发送到 {resolved_message_type} {resolved_target_id}"
            )
        else:
            return "发送图片回调未设置"

    except Exception as e:
        logger.exception(f"HTML 渲染并发送图片失败: {e}")
        return "HTML 渲染失败，请稍后重试"
