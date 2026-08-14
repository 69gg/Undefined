from __future__ import annotations

import html
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown

from Undefined.cognitive.service.helpers import _parse_profile_markdown
from Undefined.services.commands.context import CommandContext
from Undefined.utils.paths import COGNITIVE_PROFILES_DIR, RENDER_CACHE_DIR, ensure_dir

logger = logging.getLogger("profile")

_MAX_PROFILE_LENGTH = 5000
_MARKDOWN_EXTENSIONS = ["tables", "fenced_code", "sane_lists"]
_HIDDEN_FRONTMATTER_KEYS = {"source_event_id"}
_FRONTMATTER_LABELS = {
    "name": "名称",
    "tags": "标签",
    "updated_at": "更新时间",
    "entity_type": "实体类型",
    "entity_id": "编号",
    "nickname": "昵称",
    "qq": "QQ",
    "group_name": "群名",
    "group_id": "群号",
}
_FRONTMATTER_ORDER = [
    "name",
    "tags",
    "updated_at",
    "entity_type",
    "entity_id",
    "nickname",
    "qq",
    "group_name",
    "group_id",
]

_MODE_TEXT = "text"
_MODE_FORWARD = "forward"
_MODE_RENDER = "render"


def _is_private(context: CommandContext) -> bool:
    return context.scope == "private"


def _truncate(text: str, limit: int = _MAX_PROFILE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[侧写过长,已截断]"


def _parse_args(args: list[str]) -> tuple[str, str, str]:
    """解析参数，返回 (子命令, 输出模式, 目标ID)。

    目标 ID 为纯数字参数，仅超级管理员可使用。
    """
    sub = ""
    mode = ""
    target = ""
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
        elif arg.strip().isdigit():
            target = arg.strip()
    return sub, mode, target


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


def _markdown_to_html(markdown_text: str) -> str:
    return str(markdown.markdown(markdown_text, extensions=_MARKDOWN_EXTENSIONS))


def _format_frontmatter_value(key: str, value: Any) -> str:
    if key == "entity_type":
        mapping = {"user": "用户", "group": "群聊"}
        text = str(value or "").strip().lower()
        return mapping.get(text, str(value).strip())
    if key == "tags":
        if isinstance(value, list):
            return "、".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def _render_meta_rows(
    frontmatter: dict[str, Any] | None, profile_len: int
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if frontmatter:
        name = str(frontmatter.get("name") or "").strip()
        entity_id = str(frontmatter.get("entity_id") or "").strip()
        seen: set[str] = set()
        ordered_keys = [key for key in _FRONTMATTER_ORDER if key in frontmatter]
        ordered_keys.extend(
            str(key)
            for key in frontmatter
            if str(key) not in _FRONTMATTER_ORDER and str(key) not in seen
        )
        for key in ordered_keys:
            key_text = str(key)
            if key_text in _HIDDEN_FRONTMATTER_KEYS or key_text in seen:
                continue
            seen.add(key_text)
            raw_value = frontmatter.get(key)
            if key_text == "nickname" and str(raw_value or "").strip() == name:
                continue
            if key_text == "group_name" and str(raw_value or "").strip() == name:
                continue
            if key_text == "qq" and str(raw_value or "").strip() == entity_id:
                continue
            if key_text == "group_id" and str(raw_value or "").strip() == entity_id:
                continue
            formatted = _format_frontmatter_value(key_text, raw_value)
            if not formatted:
                continue
            rows.append((_FRONTMATTER_LABELS.get(key_text, key_text), formatted))
    rows.append(("长度", f"{profile_len} 字"))
    return rows


def _split_profile_for_render(
    profile_text: str,
) -> tuple[dict[str, Any] | None, str, str, str]:
    parsed = _parse_profile_markdown(profile_text)
    if parsed is None:
        return None, "", profile_text, ""
    frontmatter, evaluation, body, roast = parsed
    return frontmatter, evaluation, body or "", roast


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
    history_message = (
        f"[命令输出] /profile 合并转发\n{metadata}\n\n{_truncate(profile_text)}"
    )
    send_forward = getattr(context.sender, "send_group_forward_message", None)
    if callable(send_forward):
        await send_forward(
            context.group_id,
            nodes,
            history_message=history_message,
        )
        return
    await context.onebot.send_forward_msg(context.group_id, nodes)


async def _send_render(
    context: CommandContext,
    profile_text: str,
) -> None:
    """渲染为图片发送：YAML 键值表、独立评价区、Markdown 正文、锐评在最后。"""
    from Undefined.render import render_html_to_image

    frontmatter, evaluation, body, roast = _split_profile_for_render(profile_text)
    meta_rows_html = ""
    for key, val in _render_meta_rows(frontmatter, len(profile_text)):
        meta_rows_html += (
            f'<tr><td class="mk">{html.escape(key)}</td>'
            f'<td class="mv">{html.escape(val)}</td></tr>\n'
        )

    eval_html = ""
    if evaluation.strip():
        eval_html = (
            '<div class="eval">'
            '<div class="eval-title">评价</div>'
            f"<p>{html.escape(evaluation.strip())}</p>"
            "</div>"
        )

    body_html = _markdown_to_html(body) if body.strip() else ""

    roast_html = ""
    if roast.strip():
        roast_html = (
            '<div class="roast">'
            '<div class="roast-title">锐评</div>'
            f"<p>{html.escape(roast.strip())}</p>"
            "</div>"
        )

    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
  background: #f9f5f1; color: #3d3935; padding: 16px;
}}
.card {{
  width: 100%;
  background: #fff; border-radius: 10px;
  border: 1px solid #e6e0d8;
  overflow: hidden;
}}
.meta {{
  background: #f9f5f1; border-bottom: 1px solid #e6e0d8;
  padding: 14px 18px;
}}
.meta table {{ border-collapse: collapse; width: 100%; }}
.mk {{
  font-size: 14px; color: #6e675f; padding: 3px 12px 3px 0;
  white-space: nowrap; vertical-align: top; font-weight: 600;
}}
.mv {{
  font-size: 14px; color: #3d3935; padding: 3px 0;
  overflow-wrap: anywhere;
}}
.eval {{
  padding: 14px 18px 6px;
  border-bottom: 1px solid #e6e0d8;
}}
.eval-title {{
  font-size: 13px; font-weight: 700; color: #6e675f;
  margin-bottom: 6px;
}}
.eval p {{
  font-size: 15px; line-height: 1.7; color: #3d3935;
}}
.body {{
  padding: 18px; line-height: 1.8; font-size: 15px;
  overflow-wrap: anywhere;
}}
.roast {{
  padding: 14px 18px 16px;
  border-top: 1px solid #e6e0d8;
  border-left: 4px solid #c4a484;
  background: #f9f5f1;
}}
.roast-title {{
  font-size: 13px; font-weight: 700; color: #6e675f;
  margin-bottom: 6px;
}}
.roast p {{
  font-size: 15px; line-height: 1.7; color: #3d3935;
  font-style: italic;
}}
.doc-body > :first-child {{ margin-top: 0; }}
.doc-body > :last-child {{ margin-bottom: 0; }}
.doc-body p {{ margin: 8px 0; }}
.doc-body ul, .doc-body ol {{ margin: 8px 0; padding-left: 22px; }}
.doc-body li + li {{ margin-top: 4px; }}
.doc-body pre {{
  margin: 10px 0;
  padding: 10px 12px;
  border: 1px solid #e6e0d8;
  border-radius: 6px;
  background: #3d3935;
  color: #f9f5f1;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}}
.doc-body pre code {{
  padding: 0; border: 0; background: transparent; color: inherit;
}}
.doc-body table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
.doc-body th, .doc-body td {{
  padding: 7px 8px;
  border: 1px solid #e6e0d8;
  text-align: left;
  vertical-align: top;
}}
.doc-body th {{ background: #f3ece4; color: #3d3935; }}
.doc-body blockquote {{
  margin: 10px 0;
  padding: 8px 12px;
  border-left: 4px solid #c4a484;
  background: #f9f5f1;
}}
</style></head>
<body>
<div class="card">
  <div class="meta"><table>{meta_rows_html}</table></div>
  {eval_html}
  <div class="body"><article class="doc-body">{body_html}</article></div>
  {roast_html}
</div>
</body></html>"""

    output_dir = ensure_dir(RENDER_CACHE_DIR)
    output_path = str(output_dir / f"profile_{uuid.uuid4().hex[:8]}.png")
    await render_html_to_image(html_content, output_path, viewport_width=480)

    abs_path = Path(output_path).resolve()
    image_cq = f"[CQ:image,file=file://{abs_path}]"

    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, image_cq)
    else:
        await context.sender.send_group_message(context.group_id, image_cq)


async def _handle_render_fallback(
    context: CommandContext,
    metadata: str,
    profile_text: str,
) -> None:
    if _is_private(context):
        await _send_text(context, profile_text)
        return

    try:
        await _send_forward(context, metadata, profile_text)
    except Exception:
        logger.exception("渲染侧写图片失败后发送合并转发也失败，回退到纯文本")
        await _send_text(context, profile_text)


# ── 入口 ─────────────────────────────────────────────────────


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /profile 命令。

      用法: /p [g] [-t|--text] [-f|--forward] [-r|--render] [目标ID]
    g / group      查看群聊侧写（仅群聊可用）
    -t / --text    纯文本直接发出
          -f / --forward 合并转发发出
          -r / --render  渲染为图片发出（默认）
    目标ID          指定查询对象（仅超级管理员）
    """
    cognitive_service = context.cognitive_service
    if cognitive_service is None:
        await _send_text(context, "❌ 侧写服务未启用")
        return

    sub, mode, target = _parse_args(args)

    # 超管指定目标
    if target:
        if not context.check_permission("superadmin"):
            await _send_text(context, "❌ 仅超级管理员可查看他人侧写")
            return

    if sub in ("group", "g"):
        if _is_private(context) and not target:
            await _send_text(context, "❌ 私聊中不支持查看群聊侧写（可指定群号）")
            return
        entity_type = "group"
        entity_id = target or str(context.group_id)
        empty_hint = "暂无群聊侧写数据"
    else:
        entity_type = "user"
        entity_id = target or str(context.sender_id)
        empty_hint = "暂无侧写数据"

    profile = await cognitive_service.get_profile(entity_type, entity_id)
    if not profile:
        await _send_text(context, f"📭 {empty_hint}")
        return

    profile = _truncate(profile)
    metadata = _build_metadata(entity_type, entity_id, len(profile))

    # 未指定模式：默认渲染图片
    if not mode:
        mode = _MODE_RENDER

    if mode == _MODE_TEXT:
        await _send_text(context, profile)
    elif mode == _MODE_RENDER:
        try:
            await _send_render(context, profile)
        except Exception:
            logger.exception("渲染侧写图片失败，回退到合并转发")
            await _handle_render_fallback(context, metadata, profile)
    else:
        if _is_private(context):
            await _send_text(context, profile)
            return
        try:
            await _send_forward(context, metadata, profile)
        except Exception:
            logger.exception("发送合并转发失败，回退到纯文本")
            await _send_text(context, profile)
