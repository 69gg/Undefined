from typing import Any, Dict
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    html_content = args.get("html_content", "")
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    if not html_content:
        return "HTML 内容不能为空"
    if not target_id:
        return "目标 ID 不能为空"
    if not message_type:
        return "消息类型不能为空"
    if message_type not in ["group", "private"]:
        return "消息类型必须是 group 或 private"

    try:
        filename = f"render_{uuid.uuid4().hex[:16]}.png"
        filepath = Path.cwd() / "img" / filename
        filepath.parent.mkdir(exist_ok=True)

        render_html_to_image = context.get("render_html_to_image")
        if not render_html_to_image:
            return "错误：渲染函数 (render_html_to_image) 未在上下文中提供，请检查 AIClient 配置。"

        await render_html_to_image(html_content, str(filepath))

        send_image_callback = context.get("send_image_callback")
        if send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            return f"HTML 图片已渲染并发送到 {message_type} {target_id}"
        else:
            return "发送图片回调未设置"

    except Exception as e:
        logger.exception(f"HTML 渲染并发送图片失败: {e}")
        return f"HTML 渲染失败: {e}"
