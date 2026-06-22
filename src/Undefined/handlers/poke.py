"""拍一拍（poke）通知处理 mixin。

负责私聊/群聊拍一拍历史写入与 AI 回复触发；由 ``MessageHandler`` 混入使用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.onebot import OneBotClient
    from Undefined.services.coordinator import AICoordinator
    from Undefined.utils.history import MessageHistoryManager

logger = logging.getLogger(__name__)


def _format_poke_history_text(display_name: str, user_id: int) -> str:
    """格式化拍一拍历史文本。"""
    return f"{display_name}(暱称)[{user_id}(QQ号)] 拍了拍你。"


@dataclass(frozen=True)
class PrivatePokeRecord:
    """私聊拍一拍历史记录摘要。"""

    poke_text: str
    sender_name: str


@dataclass(frozen=True)
class GroupPokeRecord:
    """群聊拍一拍历史记录摘要。"""

    poke_text: str
    sender_name: str
    group_name: str
    sender_role: str
    sender_title: str
    sender_level: str


class PokeMixin:
    """拍一拍事件处理 mixin。"""

    if TYPE_CHECKING:
        config: Config
        onebot: OneBotClient
        ai_coordinator: AICoordinator
        history_manager: MessageHistoryManager

        def _schedule_profile_display_name_refresh(
            self,
            *,
            task_name: str,
            sender_id: int | None = None,
            sender_name: str = "",
            group_id: int | None = None,
            group_name: str = "",
        ) -> None: ...

    async def _handle_poke_notice(self, event: dict[str, Any]) -> None:
        """处理拍一拍通知并触发对应私聊/群聊 AI 回复。"""
        # 仅处理拍机器人自身的 poke
        target_id = event.get("target_id", 0)
        if target_id != self.config.bot_qq:
            logger.debug(
                "[通知] 忽略拍一拍目标非机器人: target=%s",
                target_id,
            )
            return

        if not self.config.should_process_poke_message():
            logger.debug("[消息策略] 已关闭拍一拍处理，忽略此次 poke 事件")
            return

        poke_group_id: int = event.get("group_id", 0)
        poke_sender_id: int = event.get("user_id", 0)

        if poke_group_id == 0:
            # group_id=0 表示私聊拍一拍
            if not self.config.is_private_allowed(poke_sender_id):
                private_reason = (
                    self.config.private_access_denied_reason(poke_sender_id)
                    or "unknown"
                )
                logger.debug(
                    "[访问控制] 忽略私聊拍一拍: user=%s reason=%s (access enabled=%s)",
                    poke_sender_id,
                    private_reason,
                    self.config.access_control_enabled(),
                )
                return
        else:
            if not self.config.is_group_allowed(poke_group_id):
                group_reason = (
                    self.config.group_access_denied_reason(poke_group_id) or "unknown"
                )
                logger.debug(
                    "[访问控制] 忽略群聊拍一拍: group=%s sender=%s reason=%s (access enabled=%s)",
                    poke_group_id,
                    poke_sender_id,
                    group_reason,
                    self.config.access_control_enabled(),
                )
                return

        logger.info(
            "[通知] 收到拍一拍: group=%s sender=%s",
            poke_group_id,
            poke_sender_id,
        )
        logger.debug("[通知] 拍一拍事件数据: %s", str(event)[:200])

        if poke_group_id == 0:
            private_poke = await self._record_private_poke_history(
                poke_sender_id, event
            )
            logger.info("[通知] 私聊拍一拍，触发私聊回复")
            # 拍一拍旁路 MessageBatcher，直接走 mention 级队列
            await self.ai_coordinator.handle_private_reply(
                poke_sender_id,
                private_poke.poke_text,
                [],
                is_poke=True,
                sender_name=private_poke.sender_name,
            )
        else:
            group_poke = await self._record_group_poke_history(
                poke_group_id,
                poke_sender_id,
                event,
            )
            logger.info(
                "[通知] 群聊拍一拍，触发群聊回复: group=%s",
                poke_group_id,
            )
            await self.ai_coordinator.handle_auto_reply(
                poke_group_id,
                poke_sender_id,
                group_poke.poke_text,
                [],
                is_poke=True,
                sender_name=group_poke.sender_name,
                group_name=group_poke.group_name,
                sender_role=group_poke.sender_role,
                sender_title=group_poke.sender_title,
                sender_level=group_poke.sender_level,
            )

    async def _record_private_poke_history(
        self, user_id: int, event: dict[str, Any]
    ) -> PrivatePokeRecord:
        """记录私聊拍一拍到历史。"""
        sender = event.get("sender", {})
        sender_nickname = ""
        if isinstance(sender, dict):
            sender_nickname = str(sender.get("nickname", "")).strip()

        user_name = sender_nickname
        if not user_name:
            try:
                user_info = await self.onebot.get_stranger_info(user_id)
                if isinstance(user_info, dict):
                    user_name = str(user_info.get("nickname", "")).strip()
            except Exception as exc:
                logger.warning(
                    "[通知] 获取私聊拍一拍用户昵称失败: user=%s err=%s",
                    user_id,
                    exc,
                )

        resolved_sender_name = (sender_nickname or user_name).strip()
        display_name = resolved_sender_name or f"QQ{user_id}"
        normalized_user_name = user_name or display_name
        poke_text = _format_poke_history_text(display_name, user_id)
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_private_poke:{user_id}",
            sender_id=user_id,
            sender_name=resolved_sender_name,
        )

        try:
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=poke_text,
                display_name=display_name,
                user_name=normalized_user_name,
            )
        except Exception as exc:
            logger.warning(
                "[历史记录] 写入私聊拍一拍失败: user=%s err=%s",
                user_id,
                exc,
            )
        return PrivatePokeRecord(poke_text=poke_text, sender_name=display_name)

    async def _record_group_poke_history(
        self,
        group_id: int,
        sender_id: int,
        event: dict[str, Any],
    ) -> GroupPokeRecord:
        """记录群聊拍一拍到历史。"""
        sender = event.get("sender", {})
        sender_card = ""
        sender_nickname = ""
        sender_role = "member"
        sender_title = ""
        sender_level = ""
        if isinstance(sender, dict):
            sender_card = str(sender.get("card", "")).strip()
            sender_nickname = str(sender.get("nickname", "")).strip()
            sender_role = str(sender.get("role", "member")).strip() or "member"
            sender_title = str(sender.get("title", "")).strip()
            sender_level = str(sender.get("level", "")).strip()

        if not sender_card and not sender_nickname:
            try:
                member_info = await self.onebot.get_group_member_info(
                    group_id, sender_id
                )
                if isinstance(member_info, dict):
                    sender_card = str(member_info.get("card", "")).strip()
                    sender_nickname = str(member_info.get("nickname", "")).strip()
                    sender_role = (
                        str(member_info.get("role", "member")).strip() or "member"
                    )
                    sender_title = str(member_info.get("title", "")).strip()
                    sender_level = str(member_info.get("level", "")).strip()
            except Exception as exc:
                logger.warning(
                    "[通知] 获取拍一拍群成员信息失败: group=%s user=%s err=%s",
                    group_id,
                    sender_id,
                    exc,
                )

        group_name = ""
        try:
            group_info = await self.onebot.get_group_info(group_id)
            if isinstance(group_info, dict):
                group_name = str(group_info.get("group_name", "")).strip()
        except Exception as exc:
            logger.warning(
                "[通知] 获取拍一拍群名失败: group=%s err=%s",
                group_id,
                exc,
            )

        resolved_sender_name = (sender_card or sender_nickname).strip()
        resolved_group_name = group_name.strip()
        display_name = resolved_sender_name or f"QQ{sender_id}"
        poke_text = _format_poke_history_text(display_name, sender_id)
        normalized_group_name = resolved_group_name or f"群{group_id}"
        self._schedule_profile_display_name_refresh(
            task_name=f"profile_name_refresh_group_poke:{group_id}:{sender_id}",
            sender_id=sender_id,
            sender_name=resolved_sender_name,
            group_id=group_id,
            group_name=resolved_group_name,
        )

        try:
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=sender_id,
                text_content=poke_text,
                sender_card=sender_card,
                sender_nickname=sender_nickname,
                group_name=normalized_group_name,
                role=sender_role,
                title=sender_title,
                level=sender_level,
            )
        except Exception as exc:
            logger.warning(
                "[历史记录] 写入群聊拍一拍失败: group=%s sender=%s err=%s",
                group_id,
                sender_id,
                exc,
            )
        return GroupPokeRecord(
            poke_text=poke_text,
            sender_name=display_name,
            group_name=normalized_group_name,
            sender_role=sender_role,
            sender_title=sender_title,
            sender_level=sender_level,
        )
