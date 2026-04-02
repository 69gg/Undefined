from __future__ import annotations

from typing import Any, Dict
import logging
import uuid

from Undefined.attachments import scope_from_context
from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url

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
    return None, None, "获取成功，但缺少发送目标参数"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取指定我的世界（Minecraft）正版用户的皮肤图片链接"""
    name = args.get("name")
    render_type = args.get("type", "头像")
    overlay = args.get("overlay", True)
    size = args.get("size", 160)
    scale = args.get("scale", 6)
    delivery = str(args.get("delivery", "embed") or "embed").strip().lower()
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    if delivery not in {"embed", "send"}:
        return f"delivery 无效：{delivery}。仅支持 embed 或 send"

    url = get_xingzhige_url("/API/get_Minecraft_skins/")
    params = {
        "name": name,
        "type": render_type,
        "overlay": str(overlay).lower(),
        "size": size,
        "scale": scale,
    }

    try:
        timeout = get_request_timeout(30.0)
        response = await request_with_retry(
            "GET",
            url,
            params=params,
            timeout=timeout,
            context=context,
        )

        # 检查内容类型
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            return f"获取失败: {response.text}"

        # 保存图片到缓存
        filename = f"mc_skin_{uuid.uuid4().hex[:8]}.png"
        from Undefined.utils.paths import IMAGE_CACHE_DIR, ensure_dir

        filepath = ensure_dir(IMAGE_CACHE_DIR) / filename

        with open(filepath, "wb") as f:
            f.write(response.content)

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
                    source_kind="minecraft_skin",
                    source_ref=f"minecraft_skin:{name}",
                )
            except Exception as exc:
                logger.warning("注册 Minecraft 皮肤到附件系统失败: %s", exc)

        if delivery == "embed":
            if record is None:
                return "获取成功，但无法注册到附件系统（缺少 attachment_registry 或 scope_key）"
            return f'<pic uid="{record.uid}"/>'

        # delivery == "send"
        resolved_target_id, resolved_message_type, target_error = _resolve_send_target(
            target_id, message_type, context
        )
        if target_error or resolved_target_id is None or resolved_message_type is None:
            return target_error or "获取成功，但缺少发送目标参数"

        send_image_callback = context.get("send_image_callback")
        if send_image_callback:
            await send_image_callback(
                resolved_target_id, resolved_message_type, str(filepath)
            )
            return f"Minecraft 皮肤/头像已发送给 {resolved_message_type} {resolved_target_id}"
        return "发送图片回调未设置，图片已保存但无法发送。"

    except Exception as e:
        logger.exception(f"Minecraft 皮肤获取失败: {e}")
        return "Minecraft 皮肤获取失败，请稍后重试"
