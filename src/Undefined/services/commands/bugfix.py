"""Bug 修复归档命令（/bugfix）的实现逻辑。

本模块提供 ``BugfixCommandMixin``，供 ``CommandDispatcher`` 通过多重继承组合。
通过回溯群聊记录并调用 AI 摘要，自动生成 FAQ 归档条目。
"""

from __future__ import annotations

# 斜杠命令：目录扫描注册、权限/限流/子命令路由

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from Undefined.faq import extract_faq_title
from Undefined.onebot import (
    get_message_content,
    get_message_sender_id,
    parse_message_time,
)

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.faq import FAQStorage
    from Undefined.onebot import OneBotClient
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


class BugfixCommandMixin:
    """``/bugfix`` 命令相关方法集合，作为 ``CommandDispatcher`` 的 mixin 使用。"""

    if TYPE_CHECKING:
        ai: Any
        config: Config
        faq_storage: FAQStorage
        onebot: OneBotClient
        sender: MessageSender

    async def _handle_bugfix(
        self, group_id: int, admin_id: int, args: list[str]
    ) -> None:
        """处理 ``/bugfix`` 命令，通过分析聊天记录自动生成 FAQ 归档。"""
        parsed = self._parse_bugfix_args(args)
        if isinstance(parsed, str):
            await self.sender.send_group_message(group_id, parsed)
            return

        target_qqs, start_date, end_date, start_str, end_str = parsed

        await self.sender.send_group_message(
            group_id, "🔍 正在获取对话记录进行回溯分析..."
        )

        try:
            messages = await self._fetch_messages(
                group_id, target_qqs, start_date, end_date
            )
            if not messages:
                await self.sender.send_group_message(
                    group_id, "❌ 未找到符合条件的对话记录。"
                )
                return

            processed_text = await self._process_messages(messages)
            summary = await self._obtain_bugfix_summary(group_id, processed_text)

            title = extract_faq_title(summary)
            if not title or title == "未命名问题":
                title = await self.ai.generate_title(summary)

            faq = await self.faq_storage.create(
                group_id=group_id,
                target_qq=target_qqs[0],
                start_time=start_str,
                end_time=end_str,
                title=title,
                content=summary,
            )

            result_msg = f"✅ Bug 修复分析完成！\n\n📌 FAQ ID: {faq.id}\n📋 标题: {title}\n\n{summary}"
            await self.sender.send_group_message(group_id, result_msg)

        except Exception as e:
            error_id = uuid4().hex[:8]
            logger.exception("Bugfix 失败: error_id=%s err=%s", error_id, e)
            await self.sender.send_group_message(
                group_id,
                f"❌ Bug 修复分析失败，请稍后重试（错误码: {error_id}）",
            )

    def _parse_bugfix_args(
        self, args: list[str]
    ) -> tuple[list[int], datetime, datetime, str, str] | str:
        """解析 ``/bugfix`` 命令的参数。"""
        if len(args) < 3:
            return (
                "❌ 用法: /bugfix <QQ号|@用户1> [QQ号|@用户2] ... <开始时间> <结束时间>\n"
                "时间格式: YYYY/MM/DD/HH:MM，结束时间可用 now\n"
                "示例: /bugfix 123456 2024/12/01/09:00 now"
            )

        try:
            target_qqs = [int(arg) for arg in args[:-2]]
            start_str, end_str_raw = args[-2], args[-1]
            start_date = datetime.strptime(start_str, "%Y/%m/%d/%H:%M")

            if end_str_raw.lower() == "now":
                end_date, end_str = datetime.now(), "now"
            else:
                end_date, end_str = (
                    datetime.strptime(end_str_raw, "%Y/%m/%d/%H:%M"),
                    end_str_raw,
                )

            return target_qqs, start_date, end_date, start_str, end_str
        except ValueError:
            return "❌ 参数格式错误：QQ号应为数字或 @ 提及，时间格式应为 YYYY/MM/DD/HH:MM。"

    async def _obtain_bugfix_summary(self, group_id: int, processed_text: str) -> str:
        """利用 AI 生成聊天记录的 Bug 分析摘要。"""
        total_tokens = self.ai.count_tokens(processed_text)
        max_tokens = self.config.chat_model.max_tokens

        if total_tokens <= max_tokens:
            return str(await self.ai.summarize_chat(processed_text))

        await self.sender.send_group_message(
            group_id, f"📊 消息较长（{total_tokens} tokens），正在分段处理..."
        )
        chunks = self.ai.split_messages_by_tokens(processed_text, max_tokens)
        summaries = [await self.ai.summarize_chat(chunk) for chunk in chunks]
        return str(await self.ai.merge_summaries(summaries))

    async def _fetch_messages(
        self,
        group_id: int,
        target_qqs: list[int],
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """从 OneBot 拉取指定时间范围内目标用户的消息。"""
        batch = await self.onebot.get_group_msg_history(group_id, count=2500)
        if not batch:
            return []
        target_qqs_set = set(target_qqs)
        results = []
        for msg in batch:
            msg_time = parse_message_time(msg)
            if (
                start_date <= msg_time <= end_date
                and get_message_sender_id(msg) in target_qqs_set
            ):
                # 后台循环处理队列
                results.append(msg)
        return sorted(results, key=lambda m: m.get("time", 0))

    # 后台循环处理队列
    async def _process_messages(self, messages: list[dict[str, Any]]) -> str:
        """将原始 OneBot 消息序列化为 AI 可读的纯文本。"""
        lines = []
        for msg in messages:
            sender_id = get_message_sender_id(msg)
            msg_time = parse_message_time(msg).strftime("%Y-%m-%d %H:%M:%S")
            content = get_message_content(msg)
            text_parts = []
            for segment in content:
                seg_type, seg_data = segment.get("type", ""), segment.get("data", {})
                if seg_type == "text":
                    text_parts.append(seg_data.get("text", ""))
                elif seg_type == "image":
                    file = seg_data.get("file", "") or seg_data.get("url", "")
                    if file:
                        try:
                            url = await self.onebot.get_image(file)
                            if url:
                                res = await self.ai.analyze_multimodal(url, "image")
                                text_parts.append(
                                    f"[pic]<desc>{res.get('description', '')}</desc><text>{res.get('ocr_text', '')}</text>[/pic]"
                                )
                        except Exception:
                            text_parts.append("[pic]<desc>图片处理失败</desc>[/pic]")
                elif seg_type == "at":
                    text_parts.append(f"@{seg_data.get('qq', '')}")
            if text_parts:
                lines.append(f"[{msg_time}] {sender_id}: {''.join(text_parts)}")
        return "\n".join(lines)
