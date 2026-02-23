from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /lsfaq。"""

    _ = args
    faqs = await context.faq_storage.list_all(context.group_id)
    if not faqs:
        await context.sender.send_group_message(
            context.group_id,
            "📭 当前群组没有保存的 FAQ",
        )
        return

    lines = ["📋 FAQ 列表：", ""]
    for faq in faqs[:20]:
        lines.append(f"📌 [{faq.id}] {faq.title}")
        lines.append(f"   创建时间: {faq.created_at[:10]}")
        lines.append("")
    if len(faqs) > 20:
        lines.append(f"... 还有 {len(faqs) - 20} 条")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))
