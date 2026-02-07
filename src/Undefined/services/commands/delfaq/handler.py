from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /delfaq。"""

    if not args:
        await context.sender.send_group_message(
            context.group_id,
            "❌ 用法: /delfaq <ID>\n示例: /delfaq 20241205-001",
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
    if await context.faq_storage.delete(context.group_id, faq_id):
        await context.sender.send_group_message(
            context.group_id,
            f"✅ 已删除 FAQ: [{faq_id}] {faq.title}",
        )
        return
    await context.sender.send_group_message(context.group_id, f"❌ 删除失败: {faq_id}")
