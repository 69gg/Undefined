from __future__ import annotations

import html
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Undefined.services.commands.context import CommandContext
from Undefined.utils.paths import COGNITIVE_PROFILES_DIR, RENDER_CACHE_DIR, ensure_dir

logger = logging.getLogger("profile")

_MAX_PROFILE_LENGTH = 5000

_MODE_TEXT = "text"
_MODE_FORWARD = "forward"
_MODE_RENDER = "render"


def _is_private(context: CommandContext) -> bool:
    return context.scope == "private"


def _truncate(text: str, limit: int = _MAX_PROFILE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[侧写过长,已截断]"


def _parse_args(args: list[str]) -> tuple[str, str]:
    """解析参数，返回 (子命令, 输出模式)。"""
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
    return sub, mode


def _profile_mtime(entity_type: str, entity_id: str) -> str | None:
    """读取侧写文件最后修改时间，返回人类可读字符串。"""
    p = COGNITIVE_PROFILES_DIR / f"{entity_type}s" / f"{entity_id}.md"
    try:
        mtime = p.stat().st_mtime
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except OSError:
        return None


def _build_metadata(
    entity_type: str,
    entity_id: str,
    profile_len: int,
) -> str:
    """构建元数据摘要文本。"""
    type_label = "用户" if entity_type == "user" else "群聊"
    lines = [
        f"类型: {type_label}侧写",
        f"ID: {entity_id}",
        f"长度: {profile_len} 字",
    ]
    mtime = _profile_mtime(entity_type, entity_id)
    if mtime:
        lines.append(f"更新: {mtime}")
    return "\n".join(lines)


# ── 发送方法 ──────────────────────────────────────────────────


async def _send_text(context: CommandContext, text: str) -> None:
    """纯文本直接发送。"""
    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, text)
    else:
        await context.sender.send_group_message(context.group_id, text)


async def _send_forward(
    context: CommandContext,
    metadata: str,
    profile_text: str,
) -> None:
    """合并转发：节点1=元数据，节点2=完整侧写内容。"""
    bot_qq = str(getattr(context.config, "bot_qq", 0))

    def _node(content: str) -> dict[str, Any]:
        return {
            "type": "node",
            "data": {"name": "Undefined", "uin": bot_qq, "content": content},
        }

    nodes = [_node(metadata), _node(profile_text)]
    await context.onebot.send_forward_msg(context.group_id, nodes)


async def _send_render(
    context: CommandContext,
    metadata: str,
    profile_text: str,
) -> None:
    """渲染为图片发送——元数据区 + 侧写正文区。"""
    from Undefined.render import render_html_to_image

    safe_meta = html.escape(metadata)
    safe_body = html.escape(profile_text)

    meta_rows = ""
    for line in safe_meta.split("\n"):
        if ": " in line:
            key, _, val = line.partition(": ")
            meta_rows += (
                f'<tr><td class="mk">{key}</td><td class="mv">{val}</td></tr>\n'
            )

    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
  background: #f9f5f1; color: #3d3935; padding: 24px;
}}
.card {{
  max-width: 680px; margin: 0 auto;
  background: #fff; border-radius: 10px;
  border: 1px solid #e6e0d8;
  overflow: hidden;
}}
.meta {{
  background: #f9f5f1; border-bottom: 1px solid #e6e0d8;
  padding: 16px 20px;
}}
.meta table {{ border-collapse: collapse; }}
.mk {{
  font-size: 12px; color: #6e675f; padding: 2px 10px 2px 0;
  white-space: nowrap; vertical-align: top;
}}
.mv {{
  font-size: 12px; color: #3d3935; padding: 2px 0;
}}
.body {{
  padding: 20px; line-height: 1.75; font-size: 14px;
  white-space: pre-wrap; word-wrap: break-word;
}}
</style></head>
<body>
<div class="card">
  <div class="meta"><table>{meta_rows}</table></div>
  <div class="body">{safe_body}</div>
</div>
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
        empty_hint = "暂无群聊侧写数据"
    else:
        entity_type = "user"
        entity_id = str(context.sender_id)
        empty_hint = "暂无侧写数据"

    profile = await cognitive_service.get_profile(entity_type, entity_id)
    if not profile:
        await _send_text(context, f"📭 {empty_hint}")
        return

    profile = _truncate(profile)
    metadata = _build_metadata(entity_type, entity_id, len(profile))

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
            await _send_render(context, metadata, profile)
        except Exception:
            logger.exception("渲染侧写图片失败，回退到纯文本")
            await _send_text(context, profile)
    else:
        try:
            await _send_forward(context, metadata, profile)
        except Exception:
            logger.exception("发送合并转发失败，回退到纯文本")
            await _send_text(context, profile)
