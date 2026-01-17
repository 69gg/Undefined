from typing import Any, Dict
import logging
from pathlib import Path
import uuid
import matplotlib.pyplot as plt
import matplotlib
from Undefined.render import render_markdown_to_html, render_html_to_image

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    content = args.get("content", "")
    format_type = args.get("format", "")
    target_id = args.get("target_id")
    message_type = args.get("message_type")
    
    if not content:
        return "内容不能为空"
    if not format_type:
        return "格式类型不能为空"
    if format_type not in ["latex", "markdown"]:
        return "格式类型必须是 latex 或 markdown"
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
        
        if format_type == "latex":
            matplotlib.use('Agg')
            
            fig, ax = plt.subplots(figsize=(10, 6))
            ax.axis('off')
            
            ax.text(0.5, 0.5, content,
                   transform=ax.transAxes,
                   fontsize=12,
                   verticalalignment='center',
                   horizontalalignment='center',
                   usetex=True,
                   wrap=True)
            
            plt.tight_layout()
            plt.savefig(filepath, dpi=150, bbox_inches='tight', pad_inches=0.1)
            plt.close(fig)
            
        elif format_type == "markdown":
            try:
                html_content = await render_markdown_to_html(content)
                await render_html_to_image(html_content, str(filepath))
            except Exception as e:
                logger.exception(f"Markdown 渲染失败: {e}")
                return f"Markdown 渲染失败: {e}"
        
        send_image_callback = context.get("send_image_callback")
        sender = context.get("sender")
        
        if sender:
            # sender 暂时没有直接的 send_image 方法，但 handlers 中的 _send_image 是包装了 sender
            # 但这里我们希望直接使用 sender
            # sender.send_group_message 支持 CQ 码 [CQ:image,file=path]
            # 所以我们可以直接构造消息发送
            import os
            # 确保路径是绝对路径
            abs_path = os.path.abspath(str(filepath))
            message = f"[CQ:image,file={abs_path}]"
            
            if message_type == "group":
                await sender.send_group_message(int(target_id), message)
            elif message_type == "private":
                await sender.send_private_message(int(target_id), message)
            
            return f"图片已渲染并发送到 {message_type} {target_id}"
            
        elif send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            return f"图片已渲染并发送到 {message_type} {target_id}"
        else:
            return "发送图片回调未设置"
            
    except ImportError as e:
        missing_pkg = str(e).split("'")[1] if "'" in str(e) else "未知包"
        return f"渲染失败：缺少依赖包 {missing_pkg}，请运行: uv add {missing_pkg}"
    except Exception as e:
        logger.exception(f"渲染并发送图片失败: {e}")
        return f"渲染失败: {e}"
