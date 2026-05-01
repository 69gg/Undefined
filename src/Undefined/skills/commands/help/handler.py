from __future__ import annotations

from pathlib import Path

from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, SubcommandMeta

_DOC_MAX_CHARS = 8000


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


def _format_command_detail(command_name: str, context: CommandContext) -> str | None:
    meta = context.registry.resolve(command_name)
    if meta is None:
        return None
    if not context.registry.is_visible(meta, context):
        return None
    if _is_private_scope(context) and not meta.allow_in_private:
        return None
    if not _can_see_command(meta.permission, context.sender_id, context):
        return None

    aliases = "、".join(f"/{alias}" for alias in meta.aliases) if meta.aliases else "无"
    doc_content = _load_command_doc(meta.doc_path)
    rate_limit = meta.rate_limit

    # 标题行
    name_line = f"/{meta.name}"
    if meta.aliases:
        shortest = min(meta.aliases, key=len)
        if len(shortest) < len(meta.name):
            name_line = f"/{meta.name}(/{shortest})"
    lines = [
        f"{name_line} — {meta.description or '暂无说明'}",
    ]

    # 子命令列表
    if meta.subcommands:
        lines.append("")
        lines.append("子命令：")
        for subcmd in meta.subcommands.values():
            lines.append(_format_subcommand_detail(subcmd, meta.permission))

    # 推断规则
    inference_hint = _format_inference_hint(meta)
    if inference_hint:
        lines.append("")
        lines.append(inference_hint)

    # 元信息
    lines.append("")
    lines.append(
        f"权限：{_permission_label(meta.permission)} | "
        f"作用域：{_scope_label(meta.allow_in_private)} | "
        f"限流：{rate_limit.user}s/{rate_limit.admin}s/{rate_limit.superadmin}s"
    )
    if aliases != "无":
        lines.append(f"别名：{aliases}")

    if doc_content:
        lines.extend(["", "说明文档：", doc_content])
    return "\n".join(lines)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /help。"""
    if not args:
        await context.sender.send_group_message(
            context.group_id, _format_command_list(context)
        )
        return

    detail_text = _format_command_detail(_normalize_command_name(args[0]), context)
    if detail_text is None:
        await context.sender.send_group_message(
            context.group_id,
            f"❌ 未找到命令：{args[0]}\n请使用 /help 查看命令列表",
        )
        return
    await context.sender.send_group_message(context.group_id, detail_text)
