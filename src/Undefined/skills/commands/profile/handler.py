from __future__ import annotations

import html
import logging
import uuid
from pathlib import Path
from typing import Any

from Undefined.services.commands.context import CommandContext
from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

logger = logging.getLogger("profile")

_MAX_PROFILE_LENGTH = 3000

# 合并转发单条消息最大字符数（过长拆分）
_FORWARD_NODE_LIMIT = 2000


def _is_private(context: CommandContext) -> bool:
    return context.scope == "private"


def _truncate(text: str, limit: int = _MAX_PROFILE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[侧写过长,已截断]"


# ── 输出模式枚举 ──────────────────────────────────────────────

_MODE_TEXT = "text"
_MODE_FORWARD = "forward"
_MODE_RENDER = "render"


def _parse_args(
    args: list[str],
) -> tuple[str, str]:
    """解析参数，返回 (子命令, 输出模式)。

    子命令: "" | "g" | "group"
    输出模式: "text" | "forward" | "render"
    """
    sub = ""
    mode = ""

    for arg in args:
        lower = arg.lower().strip()
        if lower in ("-t", "--text"):
            mode = _MODE_TEXT
        elif lower in ("-f", "--forward"):
            mode = _MODE_FORWARD
        elif lower in ("-r", "--render"):
            mode = _MODE_RENDER
        elif lower in ("g", "group"):
            sub = lower
        # 忽略无法识别的参数

    return sub, mode


# ── 发送方法 ──────────────────────────────────────────────────


async def _send_text(context: CommandContext, text: str) -> None:
    """纯文本直接发送。"""
    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, text)
    else:
        await context.sender.send_group_message(context.group_id, text)


async def _send_forward(context: CommandContext, title: str, profile_text: str) -> None:
    """合并转发发送。"""
    bot_qq = str(getattr(context.config, "bot_qq", 0))
    nodes: list[dict[str, Any]] = []

    def _add_node(content: str) -> None:
        nodes.append(
            {
                "type": "node",
                "data": {"name": "Undefined", "uin": bot_qq, "content": content},
            }
        )

    _add_node(title)

    # 按长度拆分成多个节点
    remaining = profile_text
    while remaining:
        chunk = remaining[:_FORWARD_NODE_LIMIT]
        remaining = remaining[_FORWARD_NODE_LIMIT:]
        _add_node(chunk)

    await context.onebot.send_forward_msg(context.group_id, nodes)


async def _send_render(context: CommandContext, title: str, profile_text: str) -> None:
    """渲染为图片发送。"""
    from Undefined.render import render_html_to_image

    safe_title = html.escape(title)
    safe_body = html.escape(profile_text)
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
    padding: 24px; max-width: 720px; margin: 0 auto;
    background: #f8f9fa; color: #212529; line-height: 1.7;
}}
h2 {{ color: #495057; border-bottom: 2px solid #dee2e6; padding-bottom: 8px; }}
pre {{
    white-space: pre-wrap; word-wrap: break-word;
    font-family: inherit; font-size: 14px; margin: 0;
}}
</style></head><body>
<h2>{safe_title}</h2>
<pre>{safe_body}</pre>
</body></html>"""

    output_dir = ensure_dir(RENDER_CACHE_DIR)
    output_path = str(output_dir / f"profile_{uuid.uuid4().hex[:8]}.png")

    await render_html_to_image(html_content, output_path)

    abs_path = Path(output_path).resolve()
    image_cq = f"[CQ:image,file=file://{abs_path}]"

    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, image_cq)
    else:
        await context.sender.send_group_message(context.group_id, image_cq)


# ── 入口 ─────────────────────────────────────────────────────


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /profile 命令。

    用法: /p [g] [-t|--text] [-f|--forward] [-r|--render]
      g / group      查看群聊侧写（仅群聊可用）
      -t / --text    纯文本直接发出
      -f / --forward 合并转发发出（群聊默认）
      -r / --render  渲染为图片发出
    """
    cognitive_service = context.cognitive_service
    if cognitive_service is None:
        await _send_text(context, "❌ 侧写服务未启用")
        return

    sub, mode = _parse_args(args)

    if sub in ("group", "g"):
        if _is_private(context):
            await _send_text(context, "❌ 私聊中不支持查看群聊侧写")
            return
        entity_type = "group"
        entity_id = str(context.group_id)
        title = "📋 群聊侧写"
        empty_hint = "暂无群聊侧写数据"
    else:
        entity_type = "user"
        entity_id = str(context.sender_id)
        title = "📋 用户侧写"
        empty_hint = "暂无侧写数据"

    profile = await cognitive_service.get_profile(entity_type, entity_id)
    if not profile:
        await _send_text(context, f"📭 {empty_hint}")
        return

    profile = _truncate(profile)

    # 私聊始终纯文本
    if _is_private(context):
        mode = _MODE_TEXT

    # 未指定模式：群聊默认合并转发
    if not mode:
        mode = _MODE_FORWARD

    if mode == _MODE_TEXT:
        await _send_text(context, profile)
    elif mode == _MODE_RENDER:
        try:
            await _send_render(context, title, profile)
        except Exception:
            logger.exception("渲染侧写图片失败，回退到纯文本")
            await _send_text(context, profile)
    else:
        try:
            await _send_forward(context, title, profile)
        except Exception:
            logger.exception("发送合并转发失败，回退到纯文本")
            await _send_text(context, profile)
