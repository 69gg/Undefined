"""当前发送者可见的斜杠命令目录。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, CommandRegistry

_DOC_MAX_CHARS = 6000
_MATCH_RANK = {
    "name": 0,
    "alias": 1,
    "description": 2,
    "usage": 3,
    "example": 4,
    "doc": 5,
}


def permission_label(permission: str) -> str:
    labels = {
        "public": "公开",
        "admin": "管理员",
        "superadmin": "超管",
    }
    return labels.get(str(permission or "public").strip().lower(), "公开")


def sender_permission_label(context: CommandContext) -> str:
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


def is_private_scope(context: CommandContext) -> bool:
    if context.scope == "private":
        return True
    try:
        return int(context.group_id) == 0
    except (TypeError, ValueError):
        return False


def can_see_command(permission: str, sender_id: int, context: CommandContext) -> bool:
    if permission in ("public", ""):
        return True
    if permission == "superadmin":
        return bool(context.config.is_superadmin(sender_id))
    if permission == "admin":
        return bool(
            context.config.is_admin(sender_id)
            or context.config.is_superadmin(sender_id)
        )
    return True


def list_visible_commands(context: CommandContext) -> list[CommandMeta]:
    commands = context.registry.list_commands(include_hidden=False)
    if is_private_scope(context):
        commands = [item for item in commands if item.allow_in_private]
    commands = [item for item in commands if context.registry.is_visible(item, context)]
    return [
        item
        for item in commands
        if can_see_command(item.permission, context.sender_id, context)
    ]


def format_command_name(meta: CommandMeta) -> str:
    name_line = f"/{meta.name}"
    if not meta.aliases:
        return name_line
    shortest = min(meta.aliases, key=len)
    if len(shortest) >= len(meta.name):
        return name_line
    return f"/{meta.name}(/{shortest})"


def format_rate_limit(meta: CommandMeta) -> str:
    rate = meta.rate_limit

    def _slot(seconds: int, label: str) -> str:
        if seconds <= 0:
            return f"{label}无限制"
        return f"{label}{seconds}s"

    return " / ".join(
        [
            _slot(rate.user, "普通"),
            _slot(rate.admin, "管理员"),
            _slot(rate.superadmin, "超管"),
        ]
    )


def load_command_doc(meta: CommandMeta, *, max_chars: int = _DOC_MAX_CHARS) -> str:
    if meta.doc_path is None or not meta.doc_path.exists():
        return ""
    content = meta.doc_path.read_text(encoding="utf-8").strip()
    if len(content) <= max_chars:
        return content
    trimmed = content[: max_chars - 32].rstrip()
    return f"{trimmed}\n\n[文档过长，已截断]"


def format_command_detail(meta: CommandMeta) -> str:
    aliases = "、".join(f"/{alias}" for alias in meta.aliases) if meta.aliases else "无"
    lines = [
        f"{format_command_name(meta)} — {meta.description or '暂无说明'}",
        "",
        f"用法：{meta.usage}",
    ]
    if meta.example:
        lines.append(f"示例：{meta.example}")
    lines.append(
        f"权限：{permission_label(meta.permission)} | "
        f"作用域：{'群聊/私聊' if meta.allow_in_private else '仅群聊'} | "
        f"限流：{format_rate_limit(meta)}"
    )
    if aliases != "无":
        lines.append(f"别名：{aliases}")
    if meta.subcommands:
        lines.append("")
        lines.append("子命令：")
        for subcmd in meta.subcommands.values():
            args_str = f" {subcmd.args}" if subcmd.args else ""
            perm_mark = ""
            if subcmd.permission != meta.permission:
                perm_mark = f"  [{permission_label(subcmd.permission)}]"
            lines.append(
                f"  {subcmd.name}{args_str}  —  {subcmd.description}{perm_mark}"
            )
    doc_content = load_command_doc(meta)
    if doc_content:
        lines.extend(["", "说明文档：", doc_content])
    return "\n".join(lines)


def format_available_commands_prompt(context: CommandContext) -> str:
    commands = list_visible_commands(context)
    scope_hint = "私聊" if is_private_scope(context) else "群聊"
    perm_hint = sender_permission_label(context)
    if not commands:
        return (
            "【当前发送者可用斜杠命令】\n"
            f"会话：{scope_hint} | 权限：{perm_hint}\n"
            "当前没有可展示的斜杠命令。\n"
            "需要限流、权限、用法或文档时调用 commands.search / commands.get；"
            "不要编造命令，也不要代替用户发送斜杠命令。"
        )
    command_lines: list[str] = []
    for item in commands:
        desc = item.description or "暂无说明"
        if item.subcommands:
            desc += f"（{len(item.subcommands)}个子命令）"
        command_lines.append(f"{format_command_name(item)} — {desc}")
    return "\n".join(
        [
            "【当前发送者可用斜杠命令】",
            f"会话：{scope_hint} | 权限：{perm_hint}",
            *command_lines,
            "需要限流、权限、用法或文档时调用 commands.search / commands.get；"
            "不要编造命令，也不要代替用户发送斜杠命令。",
        ]
    )


def _normalize_query(text: str) -> str:
    return text.strip().lstrip("/").lower()


def _match_rank(meta: CommandMeta, query: str) -> int | None:
    needle = _normalize_query(query)
    if not needle:
        return None
    if needle in meta.name.lower():
        return _MATCH_RANK["name"]
    for alias in meta.aliases:
        if needle in alias.lower():
            return _MATCH_RANK["alias"]
    if needle in (meta.description or "").lower():
        return _MATCH_RANK["description"]
    if needle in (meta.usage or "").lower():
        return _MATCH_RANK["usage"]
    if needle in (meta.example or "").lower():
        return _MATCH_RANK["example"]
    for subcmd in meta.subcommands.values():
        haystack = " ".join([subcmd.name, subcmd.description, subcmd.args]).lower()
        if needle in haystack:
            return _MATCH_RANK["description"]
    doc = load_command_doc(meta)
    if needle in doc.lower():
        return _MATCH_RANK["doc"]
    return None


def search_visible_commands(context: CommandContext, query: str) -> list[CommandMeta]:
    needle = _normalize_query(query)
    if not needle:
        return []
    scored: list[tuple[int, int, str, CommandMeta]] = []
    for meta in list_visible_commands(context):
        rank = _match_rank(meta, needle)
        if rank is None:
            continue
        scored.append((rank, meta.order, meta.name, meta))
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in scored]


def resolve_visible_command(
    context: CommandContext, command_name: str
) -> CommandMeta | None:
    normalized = _normalize_query(command_name)
    if not normalized:
        return None
    meta = context.registry.resolve(normalized)
    if meta is None:
        return None
    visible = {item.name for item in list_visible_commands(context)}
    if meta.name not in visible:
        return None
    return meta


def make_viewer_context(
    registry: CommandRegistry,
    config: Any,
    *,
    sender_id: int,
    scope: str,
    group_id: int = 0,
    user_id: int | None = None,
    is_webui_session: bool = False,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=config,
        sender=stub,
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=registry,
        scope=scope,
        user_id=user_id,
        is_webui_session=is_webui_session,
    )


class CommandCatalog:
    """面向 Prompt 与工具的可见命令查询入口。"""

    def __init__(self, registry: CommandRegistry, config: Any) -> None:
        self.registry = registry
        self.config = config

    def viewer_from_mapping(self, mapping: dict[str, Any] | None) -> CommandContext:
        data = mapping if isinstance(mapping, dict) else {}
        request_type = str(data.get("request_type") or "").strip().lower()
        is_private = bool(data.get("is_private_chat")) or request_type == "private"
        group_id = 0
        raw_group_id = data.get("group_id")
        if raw_group_id is not None:
            try:
                group_id = int(raw_group_id)
            except (TypeError, ValueError):
                group_id = 0
        if is_private:
            scope = "private"
            group_id = 0
        else:
            scope = "group" if group_id else "private"
        sender_id = 0
        for key in ("sender_id", "user_id"):
            raw = data.get(key)
            if raw is None:
                continue
            try:
                sender_id = int(raw)
            except (TypeError, ValueError):
                continue
            if sender_id:
                break
        user_id: int | None = None
        raw_user_id = data.get("user_id")
        if raw_user_id is not None:
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                user_id = None
        return make_viewer_context(
            self.registry,
            self.config,
            sender_id=sender_id,
            scope=scope,
            group_id=group_id,
            user_id=user_id,
            is_webui_session=bool(data.get("webui_session")),
        )

    def list_visible(self, context: CommandContext) -> list[CommandMeta]:
        return list_visible_commands(context)

    def format_prompt_block(self, context: CommandContext) -> str:
        return format_available_commands_prompt(context)

    def search(self, context: CommandContext, query: str) -> list[CommandMeta]:
        return search_visible_commands(context, query)

    def get(self, context: CommandContext, command_name: str) -> CommandMeta | None:
        return resolve_visible_command(context, command_name)

    def format_detail(self, meta: CommandMeta) -> str:
        return format_command_detail(meta)

    def format_name(self, meta: CommandMeta) -> str:
        return format_command_name(meta)
