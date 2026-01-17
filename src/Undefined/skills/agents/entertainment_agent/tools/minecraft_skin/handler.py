from typing import Any, Dict
import httpx
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    name = args.get("name")
    render_type = args.get("type", "头像")
    overlay = args.get("overlay", True)
    size = args.get("size", 160)
    scale = args.get("scale", 6)
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    url = "https://api.xingzhige.com/API/get_Minecraft_skins/"
    params = {
        "name": name,
        "type": render_type,
        "overlay": str(overlay).lower(),
        "size": size,
        "scale": scale,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)

            # 检查内容类型
            content_type = response.headers.get("content-type", "")

            if "application/json" in content_type:
                return f"获取失败: {response.text}"

            # 假设是图片
            filename = f"mc_skin_{uuid.uuid4().hex[:8]}.png"
            filepath = Path.cwd() / "img" / filename
            filepath.parent.mkdir(exist_ok=True)

            with open(filepath, "wb") as f:
                f.write(response.content)

            send_image_callback = context.get("send_image_callback")
            if send_image_callback:
                await send_image_callback(target_id, message_type, str(filepath))
                return f"Minecraft 皮肤/头像已发送给 {message_type} {target_id}"
            else:
                return "发送图片回调未设置，图片已保存但无法发送。"

    except Exception as e:
        logger.exception(f"Minecraft 皮肤获取失败: {e}")
        return f"Minecraft 皮肤获取失败: {e}"
