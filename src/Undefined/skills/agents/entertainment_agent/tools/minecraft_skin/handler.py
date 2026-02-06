from typing import Any, Dict
import logging
import uuid

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import get_request_timeout, get_xingzhige_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取指定我的世界（Minecraft）正版用户的皮肤图片链接"""
    name = args.get("name")
    render_type = args.get("type", "头像")
    overlay = args.get("overlay", True)
    size = args.get("size", 160)
    scale = args.get("scale", 6)
    target_id = args.get("target_id")
    message_type = args.get("message_type")

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

        # 假设是图片
        filename = f"mc_skin_{uuid.uuid4().hex[:8]}.png"
        from Undefined.utils.paths import IMAGE_CACHE_DIR, ensure_dir

        filepath = ensure_dir(IMAGE_CACHE_DIR) / filename

        with open(filepath, "wb") as f:
            f.write(response.content)

        send_image_callback = context.get("send_image_callback")
        if send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            return f"Minecraft 皮肤/头像已发送给 {message_type} {target_id}"
        return "发送图片回调未设置，图片已保存但无法发送。"

    except Exception as e:
        logger.exception(f"Minecraft 皮肤获取失败: {e}")
        return f"Minecraft 皮肤获取失败: {e}"
