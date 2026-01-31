from typing import Any, Dict
import logging
import uuid
import matplotlib.pyplot as plt
import matplotlib

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
        from Undefined.utils.cache import cleanup_cache_dir
        from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

        filename = f"render_{uuid.uuid4().hex[:16]}.png"
        filepath = ensure_dir(RENDER_CACHE_DIR) / filename

        matplotlib.use("Agg")

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.axis("off")

        ax.text(
            0.5,
            0.5,
            content,
            transform=ax.transAxes,
            fontsize=12,
            verticalalignment="center",
            horizontalalignment="center",
            usetex=True,
            wrap=True,
        )

        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)

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

            cleanup_cache_dir(RENDER_CACHE_DIR)
            return f"LaTeX 图片已渲染并发送到 {message_type} {target_id}"

        elif send_image_callback:
            await send_image_callback(target_id, message_type, str(filepath))
            cleanup_cache_dir(RENDER_CACHE_DIR)
            return f"LaTeX 图片已渲染并发送到 {message_type} {target_id}"
        else:
            return "发送图片回调未设置"

    except ImportError as e:
        missing_pkg = str(e).split("'")[1] if "'" in str(e) else "未知包"
        return f"渲染失败：缺少依赖包 {missing_pkg}，请运行: uv add {missing_pkg}"
    except Exception as e:
        logger.exception(f"渲染并发送 LaTeX 图片失败: {e}")
        return f"渲染失败: {e}"
