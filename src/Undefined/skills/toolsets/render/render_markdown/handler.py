from typing import Any, Dict
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    content = args.get("content", "")
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    if not content:
        return "内容不能为空"
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

        render_markdown_to_html = context.get("render_markdown_to_html")
        render_html_to_image = context.get("render_html_to_image")

        if not render_markdown_to_html or not render_html_to_image:
            return "错误：渲染函数 (render_markdown/render_html) 未在上下文中提供。"

        try:
            html_content = await render_markdown_to_html(content)
            await render_html_to_image(html_content, str(filepath))
        except Exception as e:
            logger.exception(f"Markdown 渲染失败: {e}")
            return f"Markdown 渲染失败: {e}"

        send_image_callback = context.get("send_image_callback")
        sender = context.get("sender")

        if sender:
            import os

            abs_path = os.path.abspath(str(filepath))
            message = f"[CQ:image,file={abs_path}]"

            if message_type == "group":
                await sender.send_group_message(int(target_id), message)
            elif message_type == "private":
                await sender.send_private_message(int(target_id), message)

            return f"Markdown 图片已渲染并发送到 {message_type} {target_id}"

        elif send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            return f"Markdown 图片已渲染并发送到 {message_type} {target_id}"
        else:
            return "发送图片回调未设置"

    except ImportError as e:
        missing_pkg = str(e).split("'")[1] if "'" in str(e) else "未知包"
        return f"渲染失败：缺少依赖包 {missing_pkg}，请运行: uv add {missing_pkg}"
    except Exception as e:
        logger.exception(f"渲染并发送 Markdown 图片失败: {e}")
        return f"渲染失败: {e}"
