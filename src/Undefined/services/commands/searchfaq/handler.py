from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /searchfaq。"""

    if not args:
        await context.sender.send_group_message(
            context.group_id,
            "❌ 用法: /searchfaq <关键词>\n示例: /searchfaq 登录",
        )
        return
    keyword = " ".join(args)
    results = await context.faq_storage.search(context.group_id, keyword)
    if not results:
        await context.sender.send_group_message(
            context.group_id,
            f'🔍 未找到包含 "{keyword}" 的 FAQ',
        )
        return
    lines = [f'🔍 搜索 "{keyword}" 找到 {len(results)} 条结果：', ""]
    for faq in results[:10]:
        lines.append(f"📌 [{faq.id}] {faq.title}")
        lines.append("")
    if len(results) > 10:
        lines.append(f"... 还有 {len(results) - 10} 条")
    lines.append("\n使用 /viewfaq <ID> 查看详情")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))
