from __future__ import annotations

import re

from Undefined.services.commands.context import CommandContext

_FAQ_ID_RE = re.compile(r"^\d{8}-\d{3}$")

_SUBCOMMANDS = {"ls", "view", "search", "del"}

_USAGE_TEXT = (
    "用法：/faq [ls|view|search|del] [参数]\n"
    "子命令：ls（列表）、view <ID>（查看）、search <关键词>（搜索）、del <ID>（删除，需管理员）\n"
    "自动推断：无参数→ls，ID格式→view，非ID→search"
)


def _infer_subcommand(args: list[str]) -> tuple[str, list[str]]:
    """根据参数自动推断子命令。"""
    if not args:
        return ("ls", [])
    first = args[0]
    if _FAQ_ID_RE.match(first):
        return ("view", args)
    return ("search", args)


async def _send(message: str, context: CommandContext) -> None:
    await context.sender.send_group_message(context.group_id, message)


async def _handle_ls(context: CommandContext) -> None:
    faqs = await context.faq_storage.list_all(context.group_id)
    if not faqs:
        await _send("📭 当前群组没有保存的 FAQ", context)
        return

    lines = ["📋 FAQ 列表：", ""]
    for faq in faqs[:20]:
        lines.append(f"📌 [{faq.id}] {faq.title}")
        lines.append(f"   创建时间: {faq.created_at[:10]}")
        lines.append("")
    if len(faqs) > 20:
        lines.append(f"... 还有 {len(faqs) - 20} 条")
    await _send("\n".join(lines), context)


async def _handle_view(args: list[str], context: CommandContext) -> None:
    if not args:
        await _send("❌ 用法: /faq view <ID>\n示例: /faq 20241205-001", context)
        return
    faq_id = args[0]
    faq = await context.faq_storage.get(context.group_id, faq_id)
    if not faq:
        await _send(f"❌ FAQ 不存在: {faq_id}", context)
        return
    message = (
        f"📖 FAQ: {faq.title}\n\n"
        f"🆔 ID: {faq.id}\n"
        f"👤 分析对象: {faq.target_qq}\n"
        f"📅 时间范围: {faq.start_time} ~ {faq.end_time}\n"
        f"🕐 创建时间: {faq.created_at}\n\n"
        f"{faq.content}"
    )
    await _send(message, context)


async def _handle_search(args: list[str], context: CommandContext) -> None:
    if not args:
        await _send("❌ 用法: /faq search <关键词>\n示例: /faq 登录", context)
        return
    keyword = " ".join(args)
    results = await context.faq_storage.search(context.group_id, keyword)
    if not results:
        await _send(f'🔍 未找到包含 "{keyword}" 的 FAQ', context)
        return
    lines = [f'🔍 搜索 "{keyword}" 找到 {len(results)} 条结果：', ""]
    for faq in results[:10]:
        lines.append(f"📌 [{faq.id}] {faq.title}")
        lines.append("")
    if len(results) > 10:
        lines.append(f"... 还有 {len(results) - 10} 条")
    lines.append("\n使用 /faq <ID> 查看详情")
    await _send("\n".join(lines), context)


async def _handle_del(args: list[str], context: CommandContext) -> None:
    if not context.config.is_admin(
        context.sender_id
    ) and not context.config.is_superadmin(context.sender_id):
        await _send("⚠️ 权限不足：只有管理员可以删除 FAQ", context)
        return
    if not args:
        await _send("❌ 用法: /faq del <ID>\n示例: /faq del 20241205-001", context)
        return
    faq_id = args[0]
    faq = await context.faq_storage.get(context.group_id, faq_id)
    if not faq:
        await _send(f"❌ FAQ 不存在: {faq_id}", context)
        return
    if await context.faq_storage.delete(context.group_id, faq_id):
        await _send(f"✅ 已删除 FAQ: [{faq_id}] {faq.title}", context)
        return
    await _send(f"❌ 删除失败: {faq_id}", context)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /faq。"""
    if not args:
        await _handle_ls(context)
        return

    first = args[0].lower()

    if first in _SUBCOMMANDS:
        subcommand = first
        sub_args = args[1:]
    else:
        subcommand, sub_args = _infer_subcommand(args)

    if subcommand == "ls":
        await _handle_ls(context)
    elif subcommand == "view":
        await _handle_view(sub_args, context)
    elif subcommand == "search":
        await _handle_search(sub_args, context)
    elif subcommand == "del":
        await _handle_del(sub_args, context)
    else:
        await _send(_USAGE_TEXT, context)
