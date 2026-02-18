"""模型切换命令处理器"""

from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /model 命令"""
    if not context.config.model_pool_enabled:
        await context.sender.send_group_message(
            context.group_id,
            "多模型功能未启用，请在 config.toml 中设置 models.pool_enabled = true",
        )
        return

    selector = context.ai.model_selector
    chat_config = context.config.chat_model
    group_id = context.group_id
    user_id = context.sender_id

    if not args:
        # 显示当前模型和可用模型列表
        current_pref = selector.get_preference(group_id, user_id, "chat")
        current = current_pref or chat_config.model_name
        lines = [f"当前模型: {current}"]
        lines.append(f"主模型: {chat_config.model_name}")
        if chat_config.pool and chat_config.pool.enabled and chat_config.pool.models:
            lines.append(f"策略: {chat_config.pool.strategy}")
            lines.append("可用模型:")
            for i, entry in enumerate(chat_config.pool.models, 1):
                lines.append(f"  {i}. {entry.model_name}")
        lines.append("用法: /model <模型名|序号> 切换, /model reset 恢复默认")
        await context.sender.send_group_message(group_id, "\n".join(lines))
        return

    target = args[0].strip()

    if target == "reset":
        selector.clear_preference(group_id, user_id, "chat")
        await selector.save_preferences()
        await context.sender.send_group_message(
            group_id, f"已恢复默认模型: {chat_config.model_name}"
        )
        return

    # 查找目标模型（支持序号或名称）
    all_models = selector.get_all_chat_models(chat_config)
    matched = None
    try:
        idx = int(target)
        if 1 <= idx <= len(all_models):
            matched = all_models[idx - 1]
    except ValueError:
        for name, cfg in all_models:
            if name == target or target in name:
                matched = (name, cfg)
                break

    if matched is None:
        await context.sender.send_group_message(group_id, f"未找到模型: {target}")
        return

    selector.set_preference(group_id, user_id, "chat", matched[0])
    await selector.save_preferences()
    await context.sender.send_group_message(group_id, f"已切换到模型: {matched[0]}")
