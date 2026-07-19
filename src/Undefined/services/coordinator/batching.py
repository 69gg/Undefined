"""消息合并、分组 prompt 构建与队列投递。"""

from __future__ import annotations


import logging
from typing import TYPE_CHECKING, Any

from Undefined.services.coordinator.group import _GROUP_STRATEGY_FOOTER
from Undefined.services.coordinator.message_ids import collect_message_ids
from Undefined.services.coordinator.private import (
    _PRIVATE_STRATEGY_FOOTER,
    _WECHAT_DELIVERY_CONSTRAINTS,
)
from Undefined.services.message_batcher import BufferedMessage

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.services.message_batcher import BufferedMessage as _BufferedMessage
    from Undefined.services.model_pool import ModelPoolService
    from Undefined.services.queue_manager import QueueManager

logger = logging.getLogger(__name__)


# BatchingMixin：MessageBatcher 回调、合并 prompt 与队列路由
class BatchingMixin:
    """MessageBatcher 回调、合并 prompt 与队列路由。"""

    if TYPE_CHECKING:
        config: Config
        queue_manager: QueueManager
        model_pool: ModelPoolService

        def _format_group_message_segment(self, item: _BufferedMessage) -> str: ...
        def _format_private_message_segment(self, item: _BufferedMessage) -> str: ...

    async def handle_batched_dispatch(self, items: list[BufferedMessage]) -> None:
        """:class:`MessageBatcher` 的 flush_callback：把一批消息组装为单次请求并入队。"""
        if not items:
            return
        await self._dispatch_grouped_request(items)

    @staticmethod
    def _build_continuous_messages_note(items: list[BufferedMessage]) -> str:
        """生成"连续消息说明"段。仅在 ``len(items) >= 2`` 时使用。"""
        count = len(items)
        first_t = items[0].arrival_time
        last_t = items[-1].arrival_time
        span = max(0.0, last_t - first_t)
        return (
            f"\n\n 【连续消息说明】以上 {count} 条 <message> 是同一用户在约 "
            f"{span:.1f} 秒内连续发送的消息（按时间先后排列），代表本轮要回应的全部输入：\n"
            f" - 这些 <message> 共同构成【当前输入批次】，不要把同批前几条误判为历史旧任务；"
            f"批次之外的历史消息仍只作为背景，不能回溯拾荒\n"
            f" - 先识别每条的意图，分清是【独立请求】还是【对前一条的修正/否定/补充/打断】\n"
            f'   · 若是【多个独立的不同意图/问题】（如"先帮我查 A，再翻译 B")'
            f" → 每个都要回应，不要遗漏；与平时一样，可以多次 send_message 自然分发\n"
            f'   · 若后发是【对前发的修正/否定/补充/打断】（如"画猫" → "改成狗")'
            f" → 以最后一次明确意图为准，旧的不再执行，可简短说明已采纳更新\n"
            f'   · 拿不准时偏向"独立请求"，宁多勿漏\n'
            f" - 整批在本轮一次性处理完即可，不要为同一意图重复输出（不要"
            f'"中间一波、结尾再来一波"重复相同回复）\n'
            f" - history 中若出现与当前轮 <message> 相同的条目，视为同一来源，不要重复处理"
        )

    def _build_grouped_prompt(self, items: list[BufferedMessage]) -> str:
        """根据 BufferedMessage 列表构造合并后的完整 prompt。"""
        if not items:
            return ""
        is_private = items[0].is_private
        # prefix：拍一拍优先；否则任一 @bot
        any_poke = any(it.is_poke for it in items)
        any_at_bot = any(it.is_at_bot for it in items)
        if any_poke:
            prefix = "(用户拍了拍你) "
        elif any_at_bot:
            prefix = "(用户 @ 了你) "
        else:
            prefix = ""

        if is_private:
            segments = [self._format_private_message_segment(it) for it in items]
        else:
            segments = [self._format_group_message_segment(it) for it in items]
        runtime_constraints = (
            f"{_WECHAT_DELIVERY_CONSTRAINTS}\n"
            if is_private and items[0].channel == "wechat"
            else ""
        )
        body = runtime_constraints + prefix + "\n".join(segments)
        if len(items) >= 2:
            body += self._build_continuous_messages_note(items)
        body += _GROUP_STRATEGY_FOOTER if not is_private else _PRIVATE_STRATEGY_FOOTER
        return body

    async def _dispatch_grouped_request(self, items: list[BufferedMessage]) -> None:
        """根据一组 BufferedMessage 决定优先级、构造 prompt 并入队。

        既是单条直送路径的统一出口，也是 :class:`MessageBatcher` 的 flush_callback。
        """
        if not items:
            return
        first = items[0]
        last = items[-1]
        full_question = self._build_grouped_prompt(items)
        message_ids = collect_message_ids(items)
        any_poke = any(it.is_poke for it in items)
        any_at_bot = any(it.is_at_bot for it in items)

        if first.is_private:
            user_id = first.sender_id
            request_data: dict[str, Any] = {
                "type": "private_reply",
                "user_id": user_id,
                "sender_name": first.sender_name,
                "text": last.text,
                "full_question": full_question,
                "trigger_message_id": last.trigger_message_id,
                "message_ids": message_ids,
                "batched_count": len(items),
                "channel": first.channel,
                "address": first.address,
                "batch_scope": first.scope,
            }
            if first.batch_token is not None:
                request_data["_message_batcher_token"] = first.batch_token
            effective_config = self.model_pool.select_chat_config(
                self.config.chat_model, user_id=user_id
            )
            request_data["selected_model_name"] = effective_config.model_name
            logger.debug(
                "[私聊回复] full_question_len=%s user=%s batched=%s",
                len(full_question),
                user_id,
                len(items),
            )
            if user_id == self.config.superadmin_qq:
                # 私聊超管 → 最高优先级 superadmin lane
                await self.queue_manager.add_superadmin_request(
                    request_data, model_name=effective_config.model_name
                )
            else:
                await self.queue_manager.add_private_request(
                    request_data, model_name=effective_config.model_name
                )
            return

        # 群聊：按 sender 身份与 @bot 状态选择 4 级 lane 之一
        group_id = first.group_id or 0
        sender_id = first.sender_id
        request_data = {
            "type": "auto_reply",
            "group_id": group_id,
            "sender_id": sender_id,
            "sender_name": first.sender_name,
            "group_name": first.group_name,
            "text": last.text,
            "full_question": full_question,
            "is_at_bot": any_at_bot,
            "trigger_message_id": last.trigger_message_id,
            "message_ids": message_ids,
            "batched_count": len(items),
        }
        if first.batch_token is not None:
            request_data["_message_batcher_token"] = first.batch_token
        logger.debug(
            "[自动回复] full_question_len=%s group=%s sender=%s batched=%s",
            len(full_question),
            group_id,
            sender_id,
            len(items),
        )
        if sender_id == self.config.superadmin_qq:
            logger.info("[AI] 投递至群聊超级管理员队列 (batched=%s)", len(items))
            await self.queue_manager.add_group_superadmin_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        elif any_at_bot:
            trigger = "拍一拍" if any_poke else "@机器人"
            logger.info("[AI] 触发原因: %s (batched=%s)", trigger, len(items))
            await self.queue_manager.add_group_mention_request(
                request_data, model_name=self.config.chat_model.model_name
            )
        else:
            logger.info("[AI] 投递至普通请求队列 (batched=%s)", len(items))
            await self.queue_manager.add_group_normal_request(
                request_data, model_name=self.config.chat_model.model_name
            )
