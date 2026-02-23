from __future__ import annotations

from pathlib import Path

from Undefined.services.commands.context import CommandContext

_DOC_MAX_CHARS = 8000


def _permission_label(permission: str) -> str:
    permission_label_map = {
        "public": "公开可用",
        "admin": "仅限管理员",
        "superadmin": "仅限超级管理员",
    }
    return permission_label_map.get(permission, "公开可用")


def _format_command_list(context: CommandContext) -> str:
    commands = context.registry.list_commands(include_hidden=False)
    command_lines = [
        f"- {item.usage}：{item.description or '暂无说明'}" for item in commands
    ]

    help_meta = context.registry.resolve("help")
    footer_lines = (
        help_meta.help_footer
        if help_meta is not None and help_meta.help_footer
        else ["查看详细帮助：/help <command>", "版权与免责声明：/copyright"]
    )

    lines = ["Undefined 命令帮助", "", "可用命令：", *command_lines, "", *footer_lines]
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


def _format_command_detail(command_name: str, context: CommandContext) -> str | None:
    meta = context.registry.resolve(command_name)
    if meta is None:
        return None

    aliases = "、".join(f"/{alias}" for alias in meta.aliases) if meta.aliases else "无"
    doc_content = _load_command_doc(meta.doc_path)
    rate_limit = meta.rate_limit

    lines = [
        f"命令详情：/{meta.name}",
        "",
        f"描述：{meta.description or '暂无说明'}",
        f"用法：{meta.usage or f'/{meta.name}'}",
        f"示例：{meta.example or meta.usage or f'/{meta.name}'}",
        f"权限：{_permission_label(meta.permission)}",
        (
            "限流："
            f"user={rate_limit.user}s, admin={rate_limit.admin}s, superadmin={rate_limit.superadmin}s"
        ),
        f"别名：{aliases}",
    ]
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
