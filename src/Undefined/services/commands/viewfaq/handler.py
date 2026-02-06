from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /viewfaq。"""

    if not args:
        await context.sender.send_group_message(
            context.group_id,
            "❌ 用法: /viewfaq <ID>\n示例: /viewfaq 20241205-001",
        )
        return
    faq_id = args[0]
    faq = await context.faq_storage.get(context.group_id, faq_id)
    if not faq:
        await context.sender.send_group_message(
            context.group_id,
            f"❌ FAQ 不存在: {faq_id}",
        )
        return
    message = (
        f"📖 FAQ: {faq.title}\n\n"
        f"🆔 ID: {faq.id}\n"
        f"👤 分析对象: {faq.target_qq}\n"
        f"📅 时间范围: {faq.start_time} ~ {faq.end_time}\n"
        f"🕐 创建时间: {faq.created_at}\n\n"
        f"{faq.content}"
    )
    await context.sender.send_group_message(context.group_id, message)
