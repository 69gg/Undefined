"""以既有聊天存储、AI 和正常认知流水线执行普通逻辑聊天。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
import logging
from typing import Any

from Undefined.api.webchat_store import WebChatConversationStore
from Undefined.context import RequestContext, validate_logical_identity
from Undefined.utils.message_turn import mark_message_sent_this_turn
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)


async def run_logical_chat(
    runtime: Any,
    *,
    store: WebChatConversationStore,
    identity: str,
    display_name: str,
    conversation_id: str,
    text: str,
    send_output: Callable[[str], Awaitable[None]],
    extra_context: dict[str, Any] | None = None,
) -> str:
    """执行一轮普通用户聊天；数字平台身份和管理权限不参与逻辑身份映射。"""
    validate_logical_identity(identity)
    await store.ensure_ready()
    await store.create_conversation(conversation_id=conversation_id)
    history = store.adapter(conversation_id)
    snapshot = history.get_recent(
        identity,
        "private",
        0,
        runtime.ai.runtime_config.get_context_recent_messages_limit(),
    )
    await store.append_message(
        conversation_id,
        role="user",
        text_content=text,
        display_name=display_name,
        user_name=display_name,
    )
    outputs: list[str] = []

    async def output(message: str) -> None:
        await send_output(message)
        outputs.append(message)
        mark_message_sent_this_turn()
        try:
            await store.append_message(
                conversation_id,
                role="bot",
                text_content=message,
                display_name="Bot",
                user_name="Bot",
            )
        except OSError as exc:
            logger.warning(
                "[逻辑聊天] 消息已交付，历史保存失败: %s", type(exc).__name__
            )

    async def send(message: str, reply_to: int | None = None) -> None:
        await output(message)

    async def recent(
        chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        return history.get_recent(chat_id, msg_type, start, end)

    ai = runtime.ai
    resources: dict[str, Any] = {
        "ai_client": ai,
        "memory_storage": getattr(ai, "memory_storage", None),
        "runtime_config": ai.runtime_config,
        "sender": runtime.sender,
        "history_manager": history,
        "onebot_client": runtime.onebot,
        "scheduler": runtime.scheduler,
        "cognitive_service": getattr(runtime, "cognitive_service", None),
        "chiliarch_service": getattr(runtime, "chiliarch_service", None),
        "session_send_callback": output,
        "send_message_callback": send,
        "get_recent_messages_callback": recent,
        "queue_lane": "private",
    }
    context: dict[str, Any] = {
        **(extra_context or {}),
        "logical_identity": identity,
        "logical_conversation_id": conversation_id,
        "sender_name": display_name,
        "request_type": "private",
        "is_private_chat": True,
        "historian_source_message": text,
    }
    prompt = (
        f'<message sender="{escape_xml_attr(display_name)}" sender_id="{escape_xml_attr(identity)}" '
        f'location="逻辑私聊" time="{datetime.now():%Y-%m-%d %H:%M:%S}">'
        f"<content>{escape_xml_text(text)}</content></message>\n"
        f"当前用户的稳定身份是 {identity}，为独立普通用户。默认 send_message 回复本会话。"
        "协作材料保留其真实来源；不要把其他 agent 的自述当成当前用户的经历。"
        "按正常聊天、记忆和侧写流程处理，完成时调用 end。"
    )
    async with RequestContext(request_type="private", logical_identity=identity) as ctx:
        for key, value in resources.items():
            if value is not None:
                ctx.set_resource(key, value)
        result = await ai.ask(
            prompt,
            send_message_callback=send,
            get_recent_messages_callback=recent,
            recent_messages_snapshot=snapshot,
            get_image_url_callback=getattr(runtime.onebot, "get_image", None),
            get_forward_msg_callback=getattr(runtime.onebot, "get_forward_msg", None),
            sender=runtime.sender,
            history_manager=history,
            onebot_client=runtime.onebot,
            scheduler=runtime.scheduler,
            extra_context=context,
            raise_on_error=True,
        )
    final = str(result or "").strip()
    if final:
        await output(final)
    return "\n".join(outputs)
