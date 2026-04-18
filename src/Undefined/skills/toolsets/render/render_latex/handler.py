from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict
import logging
import uuid

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from Undefined.attachments import scope_from_context

logger = logging.getLogger(__name__)

_DOCUMENT_PATTERN = re.compile(
    r"^\s*\\begin\{document\}(?P<body>.*?)\\end\{document\}\s*$",
    re.DOTALL,
)


def _strip_document_wrappers(content: str) -> str:
    """去掉 \\begin{document}...\\end{document} 外层包装；matplotlib 会自行构造文档。"""
    text = content.strip()
    match = _DOCUMENT_PATTERN.fullmatch(text)
    if match is None:
        return text
    return match.group("body").strip()


def _render_latex_image(filepath: Path, content: str) -> None:
    text = _strip_document_wrappers(content)
    fig = plt.figure(figsize=(6, 2.5))
    try:
        fig.patch.set_facecolor("white")
        fig.text(
            0.5,
            0.5,
            text,
            fontsize=20,
            verticalalignment="center",
            horizontalalignment="center",
            usetex=True,
            wrap=True,
        )
        fig.savefig(filepath, dpi=200, bbox_inches="tight", pad_inches=0.25)
    finally:
        plt.close(fig)


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
    """渲染 LaTeX 数学公式为图片"""
    content = str(args.get("content", "") or "")
    delivery = str(args.get("delivery", "embed") or "embed").strip().lower()
    target_id = args.get("target_id")
    message_type = args.get("message_type")

    if not content:
        return "内容不能为空"
    if delivery not in {"embed", "send"}:
        return f"delivery 无效：{delivery}。仅支持 embed 或 send"

    if delivery == "send" and message_type and message_type not in ("group", "private"):
        return "消息类型必须是 group 或 private"

    try:
        from Undefined.utils.cache import cleanup_cache_dir
        from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

        filename = f"render_{uuid.uuid4().hex[:16]}.png"
        filepath = ensure_dir(RENDER_CACHE_DIR) / filename

        _render_latex_image(filepath, content)

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
                    source_ref="render_latex",
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

        sender = context.get("sender")
        send_image_callback = context.get("send_image_callback")

        if sender:
            from pathlib import Path

            cq_message = f"[CQ:image,file={Path(filepath).resolve().as_uri()}]"
            if resolved_message_type == "group":
                await sender.send_group_message(int(resolved_target_id), cq_message)
            elif resolved_message_type == "private":
                await sender.send_private_message(int(resolved_target_id), cq_message)
            cleanup_cache_dir(RENDER_CACHE_DIR)
            return (
                f"LaTeX 图片已渲染并发送到 {resolved_message_type} {resolved_target_id}"
            )
        elif send_image_callback:
            await send_image_callback(
                resolved_target_id, resolved_message_type, str(filepath)
            )
            cleanup_cache_dir(RENDER_CACHE_DIR)
            return (
                f"LaTeX 图片已渲染并发送到 {resolved_message_type} {resolved_target_id}"
            )
        else:
            return "发送图片回调未设置"

    except ImportError as e:
        missing_pkg = str(e).split("'")[1] if "'" in str(e) else "未知包"
        return f"渲染失败：缺少依赖包 {missing_pkg}，请运行: uv add {missing_pkg}"
    except RuntimeError as e:
        err = str(e).lower()
        if "latex" in err or "dvipng" in err or "dvi" in err:
            logger.error("LaTeX 渲染失败（系统 TeX 环境不可用）: %s", e)
            return "渲染失败：系统 LaTeX 环境未安装或不完整，请按部署文档安装 TeX Live / MiKTeX 后重试。"
        logger.exception("渲染并发送 LaTeX 图片失败: %s", e)
        return "渲染失败，请稍后重试"
    except Exception as e:
        logger.exception(f"渲染并发送 LaTeX 图片失败: {e}")
        return "渲染失败，请稍后重试"
