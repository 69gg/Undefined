"""多模型比较命令处理器"""

from __future__ import annotations

import asyncio

from Undefined.config.models import ChatModelConfig
from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /compare 命令"""
    if not context.config.model_pool_enabled:
        await context.sender.send_group_message(
            context.group_id,
            "多模型功能未启用，请在 config.toml 中设置 models.pool_enabled = true",
        )
        return

    if not args:
        await context.sender.send_group_message(
            context.group_id, "用法: /compare <问题>"
        )
        return

    prompt = " ".join(args)
    chat_config = context.config.chat_model
    selector = context.ai.model_selector
    all_models = selector.get_all_chat_models(chat_config)

    if len(all_models) < 2:
        await context.sender.send_group_message(
            context.group_id, "模型池中只有一个模型，无法比较"
        )
        return

    await context.sender.send_group_message(
        context.group_id, f"正在向 {len(all_models)} 个模型发送问题，请稍候..."
    )

    messages = [{"role": "user", "content": prompt}]

    async def query_model(name: str, config: ChatModelConfig) -> tuple[str, str]:
        try:
            result = await context.ai.request_model(
                model_config=config,
                messages=list(messages),
                max_tokens=config.max_tokens,
                call_type="compare",
            )
            content = (
                result.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            return name, content.strip() or "(空回复)"
        except Exception as exc:
            return name, f"(请求失败: {exc})"

    tasks = [query_model(name, cfg) for name, cfg in all_models]
    results = await asyncio.gather(*tasks)

    lines = [f"问题: {prompt}", ""]
    for i, (name, content) in enumerate(results, 1):
        if len(content) > 500:
            content = content[:497] + "..."
        lines.append(f"【{i}】{name}")
        lines.append(content)
        lines.append("")

    lines.append("回复「选2」可切换到该模型")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))

    selector.set_pending_compare(
        context.group_id, context.sender_id, [name for name, _cfg in all_models]
    )
