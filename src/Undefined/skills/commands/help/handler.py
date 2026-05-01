from __future__ import annotations

import html
import logging
import uuid
from pathlib import Path

from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, SubcommandMeta

_DOC_MAX_CHARS = 8000
_TEXT_FLAGS = {"-t", "--text", "--plain", "--plaintext", "--raw"}

logger = logging.getLogger("help")


def _permission_label(permission: str) -> str:
    permission_label_map = {
        "public": "公开",
        "admin": "管理员",
        "superadmin": "超管",
    }
    return permission_label_map.get(permission, "公开")


def _sender_permission_label(context: CommandContext) -> str:
    config = context.config
    try:
        if config.is_superadmin(context.sender_id):
            return "超管"
    except Exception:
        pass
    try:
        if config.is_admin(context.sender_id):
            return "管理员"
    except Exception:
        pass
    return "普通用户"


def _scope_label(allow_in_private: bool) -> str:
    return "群聊/私聊" if allow_in_private else "仅群聊"


def _is_private_scope(context: CommandContext) -> bool:
    return int(context.group_id) == 0


async def _send_message(context: CommandContext, message: str) -> None:
    if _is_private_scope(context):
        try:
            send_private = context.sender.send_private_message
        except AttributeError:
            send_private = None
        if send_private is not None:
            user_id = int(context.user_id or context.sender_id)
            await send_private(user_id, message)
            return
    await context.sender.send_group_message(context.group_id, message)


def _can_see_command(permission: str, sender_id: int, context: CommandContext) -> bool:
    """根据命令权限判断用户是否可见该命令。"""
    if permission in ("public", ""):
        return True
    if permission == "superadmin":
        return context.config.is_superadmin(sender_id)
    if permission == "admin":
        return context.config.is_admin(sender_id) or context.config.is_superadmin(
            sender_id
        )
    return True


def _format_usage_with_alias(item: CommandMeta) -> str:
    """格式化命令用法，自动附上最短别名（如 /changelog(/cl)）。"""
    usage = item.usage
    if not item.aliases:
        return usage
    shortest = min(item.aliases, key=len)
    if len(shortest) >= len(item.name):
        return usage
    return usage.replace(f"/{item.name}", f"/{item.name}(/{shortest})", 1)


def _format_command_list(context: CommandContext) -> str:
    commands = context.registry.list_commands(include_hidden=False)
    in_private = _is_private_scope(context)
    if in_private:
        commands = [item for item in commands if item.allow_in_private]
    commands = [item for item in commands if context.registry.is_visible(item, context)]

    # 按权限过滤：非管理员看不到管理命令
    commands = [
        item
        for item in commands
        if _can_see_command(item.permission, context.sender_id, context)
    ]

    scope_hint = "私聊" if in_private else "群聊"
    perm_hint = _sender_permission_label(context)

    command_lines = []
    for item in commands:
        line = f"/{item.name}"
        if item.aliases:
            shortest = min(item.aliases, key=len)
            if len(shortest) < len(item.name):
                line = f"/{item.name}(/{shortest})"
        desc = item.description or "暂无说明"
        # 子命令数量
        if item.subcommands:
            desc += f"({len(item.subcommands)}个子命令)"
        command_lines.append(f"{line} — {desc}")

    help_meta = context.registry.resolve("help")
    footer_lines = (
        help_meta.help_footer
        if help_meta is not None and help_meta.help_footer
        else [
            "/help <命令> 查看详情 | /copyright 版权声明",
        ]
    )

    lines = [
        "Undefined 命令帮助",
        f"会话：{scope_hint} | 权限：{perm_hint}",
        "",
        *command_lines,
        "",
        *footer_lines,
    ]
    return "\n".join(lines)


def _parse_detail_args(args: list[str]) -> tuple[str | None, bool]:
    command_name: str | None = None
    force_text = False
    for arg in args:
        normalized = arg.strip().lower()
        if normalized in _TEXT_FLAGS:
            force_text = True
            continue
        if command_name is None:
            command_name = arg
    return command_name, force_text


def _normalize_command_name(text: str) -> str:
    return text.strip().lstrip("/").lower()


def _load_command_doc(doc_path: Path | None) -> str:
    if doc_path is None or not doc_path.exists():
        return ""
    content = doc_path.read_text(encoding="utf-8").strip()
    if len(content) <= _DOC_MAX_CHARS:
        return content
    trimmed = content[: _DOC_MAX_CHARS - 32].rstrip()
    return f"{trimmed}\n\n[文档过长，已截断]"


def _format_subcommand_detail(subcmd: SubcommandMeta, parent_permission: str) -> str:
    args_str = f" {subcmd.args}" if subcmd.args else ""
    perm_mark = ""
    if subcmd.permission != parent_permission:
        perm_mark = f"  [{_permission_label(subcmd.permission)}]"
    return f"  {subcmd.name}{args_str}  —  {subcmd.description}{perm_mark}"


def _format_inference_hint(meta: CommandMeta) -> str | None:
    inference = meta.inference
    if inference is None:
        return None
    parts: list[str] = []
    if inference.default is not None:
        parts.append(f"无参数→{inference.default}")
    for rule in inference.rules:
        parts.append(f"匹配{rule.pattern.pattern}→{rule.subcommand}")
    if inference.fallback is not None:
        parts.append(f"其他→{inference.fallback}")
    return "自动推断：" + "、".join(parts) if parts else None


def _resolve_visible_command(
    command_name: str,
    context: CommandContext,
) -> CommandMeta | None:
    meta = context.registry.resolve(command_name)
    if meta is None:
        return None
    if not context.registry.is_visible(meta, context):
        return None
    if _is_private_scope(context) and not meta.allow_in_private:
        return None
    if not _can_see_command(meta.permission, context.sender_id, context):
        return None
    return meta


def _format_command_name_with_alias(meta: CommandMeta) -> str:
    name_line = f"/{meta.name}"
    if meta.aliases:
        shortest = min(meta.aliases, key=len)
        if len(shortest) < len(meta.name):
            name_line = f"/{meta.name}(/{shortest})"
    return name_line


def _format_rate_limit(meta: CommandMeta) -> str:
    rate_limit = meta.rate_limit
    return f"{rate_limit.user}s/{rate_limit.admin}s/{rate_limit.superadmin}s"


def _format_command_detail_text(meta: CommandMeta, doc_content: str) -> str:
    aliases = "、".join(f"/{alias}" for alias in meta.aliases) if meta.aliases else "无"
    name_line = _format_command_name_with_alias(meta)
    lines = [
        f"{name_line} — {meta.description or '暂无说明'}",
        "",
        f"用法：{_format_usage_with_alias(meta)}",
    ]
    if meta.example:
        lines.append(f"示例：{meta.example}")
    lines.append(
        f"权限：{_permission_label(meta.permission)} | "
        f"作用域：{_scope_label(meta.allow_in_private)} | "
        f"限流：{_format_rate_limit(meta)}"
    )
    if aliases != "无":
        lines.append(f"别名：{aliases}")

    if meta.subcommands:
        lines.append("")
        lines.append("子命令：")
        for subcmd in meta.subcommands.values():
            lines.append(_format_subcommand_detail(subcmd, meta.permission))

    inference_hint = _format_inference_hint(meta)
    if inference_hint:
        lines.append("")
        lines.append(inference_hint)

    if doc_content:
        lines.extend(["", "说明文档：", doc_content])
    return "\n".join(lines)


def _html_text(text: str) -> str:
    return html.escape(text, quote=True)


def _html_code(text: str) -> str:
    return f"<code>{_html_text(text)}</code>"


def _build_meta_item(label: str, value: str, *, code: bool = False) -> str:
    value_html = _html_code(value) if code else _html_text(value)
    return (
        '<div class="meta-item">'
        f'<span class="meta-label">{_html_text(label)}</span>'
        f'<div class="meta-value">{value_html}</div>'
        "</div>"
    )


def _format_subcommands_html(meta: CommandMeta) -> str:
    if not meta.subcommands:
        return ""
    rows: list[str] = []
    for subcmd in meta.subcommands.values():
        args_str = f" {subcmd.args}" if subcmd.args else ""
        perm_mark = ""
        if subcmd.permission != meta.permission:
            perm_mark = (
                f'<span class="badge">{_permission_label(subcmd.permission)}</span>'
            )
        rows.append(
            "<tr>"
            f"<td>{_html_code(subcmd.name + args_str)}</td>"
            f"<td>{_html_text(subcmd.description)}{perm_mark}</td>"
            "</tr>"
        )
    return (
        '<section class="section">'
        "<h2>子命令</h2>"
        '<table class="subcommands"><tbody>' + "".join(rows) + "</tbody></table>"
        "</section>"
    )


def _format_command_detail_html(meta: CommandMeta, doc_content: str) -> str:
    aliases = "、".join(f"/{alias}" for alias in meta.aliases) if meta.aliases else "无"
    inference_hint = _format_inference_hint(meta)
    meta_items = [
        _build_meta_item("用法", _format_usage_with_alias(meta), code=True),
        _build_meta_item("权限", _permission_label(meta.permission)),
        _build_meta_item("作用域", _scope_label(meta.allow_in_private)),
        _build_meta_item("限流", _format_rate_limit(meta)),
    ]
    if meta.example:
        meta_items.append(_build_meta_item("示例", meta.example, code=True))
    if aliases != "无":
        meta_items.append(_build_meta_item("别名", aliases))

    inference_section = ""
    if inference_hint:
        hint_text = inference_hint.removeprefix("自动推断：")
        inference_section = (
            '<section class="section">'
            "<h2>自动推断</h2>"
            f'<p class="hint">{_html_text(hint_text)}</p>'
            "</section>"
        )

    doc_section = ""
    if doc_content:
        doc_section = (
            '<section class="section">'
            "<h2>说明文档</h2>"
            f'<pre class="doc">{_html_text(doc_content)}</pre>'
            "</section>"
        )

    title = _format_command_name_with_alias(meta)
    description = meta.description or "暂无说明"
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            padding: 24px;
            background: #f5f7fb;
            color: #1f2937;
            font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', Arial, sans-serif;
            font-size: 15px;
            line-height: 1.65;
        }}
        .panel {{
            width: 100%;
            max-width: 720px;
            margin: 0 auto;
            background: #ffffff;
            border: 1px solid #d8dee9;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
        }}
        .header {{
            padding: 22px 26px 18px;
            border-bottom: 1px solid #e5e7eb;
            background: #f9fafb;
        }}
        .eyebrow {{
            margin: 0 0 6px;
            color: #0f766e;
            font-size: 13px;
            font-weight: 700;
        }}
        h1 {{
            margin: 0;
            color: #111827;
            font-size: 26px;
            line-height: 1.25;
            font-weight: 800;
        }}
        .description {{
            margin: 8px 0 0;
            color: #4b5563;
            font-size: 15px;
        }}
        .content {{ padding: 20px 26px 26px; }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }}
        .meta-item {{
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 10px 12px;
            background: #ffffff;
            min-width: 0;
        }}
        .meta-label {{
            display: block;
            color: #6b7280;
            font-size: 12px;
            font-weight: 700;
            margin-bottom: 4px;
        }}
        .meta-value {{ color: #111827; overflow-wrap: anywhere; }}
        code {{
            font-family: 'Cascadia Code', 'SFMono-Regular', Consolas, monospace;
            color: #075985;
            background: #eff6ff;
            border: 1px solid #dbeafe;
            border-radius: 4px;
            padding: 1px 5px;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }}
        .section {{ margin-top: 20px; }}
        h2 {{
            margin: 0 0 10px;
            color: #111827;
            font-size: 16px;
            line-height: 1.35;
        }}
        .subcommands {{ width: 100%; border-collapse: collapse; }}
        .subcommands td {{
            padding: 10px 0;
            border-top: 1px solid #e5e7eb;
            vertical-align: top;
        }}
        .subcommands td:first-child {{ width: 42%; padding-right: 14px; }}
        .badge {{
            display: inline-block;
            margin-left: 8px;
            color: #7c2d12;
            background: #ffedd5;
            border: 1px solid #fed7aa;
            border-radius: 4px;
            padding: 0 5px;
            font-size: 12px;
            font-weight: 700;
            white-space: nowrap;
        }}
        .hint {{
            margin: 0;
            padding: 10px 12px;
            border: 1px solid #ccfbf1;
            border-radius: 6px;
            background: #f0fdfa;
            color: #134e4a;
            overflow-wrap: anywhere;
        }}
        .doc {{
            margin: 0;
            padding: 14px;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            background: #f9fafb;
            color: #374151;
            font-family: 'Cascadia Code', 'SFMono-Regular', Consolas, monospace;
            font-size: 13px;
            line-height: 1.7;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }}
    </style>
</head>
<body>
    <main class="panel">
        <header class="header">
            <p class="eyebrow">Undefined 命令帮助</p>
            <h1>{_html_text(title)}</h1>
            <p class="description">{_html_text(description)}</p>
        </header>
        <div class="content">
            <div class="meta-grid">{"".join(meta_items)}</div>
            {_format_subcommands_html(meta)}
            {inference_section}
            {doc_section}
        </div>
    </main>
</body>
</html>"""


async def _send_rendered_detail(
    context: CommandContext,
    meta: CommandMeta,
    doc_content: str,
) -> None:
    from Undefined.render import render_html_to_image
    from Undefined.utils.paths import RENDER_CACHE_DIR, ensure_dir

    output_dir = ensure_dir(RENDER_CACHE_DIR)
    output_path = output_dir / f"help_{meta.name}_{uuid.uuid4().hex[:8]}.png"
    html_content = _format_command_detail_html(meta, doc_content)
    await render_html_to_image(html_content, str(output_path), viewport_width=760)
    image_cq = f"[CQ:image,file={output_path.resolve().as_uri()}]"
    await _send_message(context, image_cq)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /help。"""
    if not args:
        await _send_message(context, _format_command_list(context))
        return

    command_arg, force_text = _parse_detail_args(args)
    if command_arg is None:
        await _send_message(context, _format_command_list(context))
        return

    meta = _resolve_visible_command(_normalize_command_name(command_arg), context)
    if meta is None:
        await _send_message(
            context,
            f"❌ 未找到命令：{command_arg}\n请使用 /help 查看命令列表",
        )
        return

    doc_content = _load_command_doc(meta.doc_path)
    detail_text = _format_command_detail_text(meta, doc_content)
    if force_text:
        await _send_message(context, detail_text)
        return

    try:
        await _send_rendered_detail(context, meta, doc_content)
    except Exception:
        logger.exception("渲染命令帮助图片失败，回退到纯文本")
        await _send_message(context, detail_text)
