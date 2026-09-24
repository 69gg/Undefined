"""Bugfix（/bugfix）命令实现：读取群上下文并生成娱乐性诊断。

从 `services/command.py` 拆出，作为 `CommandDispatcher` 的 mixin。
"""

from __future__ import annotations

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
    from Undefined.ai import AIClient
    from Undefined.faq import FAQStorage
    from Undefined.config import Config
    from Undefined.onebot import OneBotClient
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


class BugfixCommandMixin:
    """`/bugfix` 命令的上下文收集与诊断实现。"""

    if TYPE_CHECKING:
        config: Config
        ai: AIClient
        sender: MessageSender
        onebot: OneBotClient
        faq_storage: FAQStorage

    async def handle_bugfix(
        self, group_id: int, admin_id: int, args: list[str]
    ) -> None:
        """处理 /bugfix 命令，通过分析聊天记录自动生成 FAQ 归档"""
        # 1. 参数解析
        parsed = self._parse_bugfix_args(args)
        if isinstance(parsed, str):
            await self.sender.send_group_message(group_id, parsed)
            return

        target_qqs, start_date, end_date, start_str, end_str = parsed

        await self.sender.send_group_message(
            group_id, "🔍 正在获取对话记录进行回溯分析..."
        )

        try:
            # 2. 获取并处理消息
            messages = await self._fetch_messages(
                group_id, target_qqs, start_date, end_date
            )
            if not messages:
                await self.sender.send_group_message(
                    group_id, "❌ 未找到符合条件的对话记录。"
                )
                return

            processed_text = await self._process_messages(messages)

            # 3. 生成摘要总结
            summary = await self._obtain_bugfix_summary(group_id, processed_text)

            # 4. 生成标题并入库
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
        """解析 bugfix 命令的参数"""
        if len(args) < 3:
            return (
                "❌ 用法: /bugfix <QQ号|@用户1> [QQ号|@用户2] ... <开始时间> <结束时间>\n"
                "时间格式: YYYY/MM/DD/HH:MM，结束时间可用 now\n"
                "示例: /bugfix 123456 2024/12/01/09:00 now"
            )

        try:
            # 防御性归一化：常规路径 parse_command 已把 [@QQ号(昵称)] 转成纯数字，
            # 这里兜底支持未经过该层的直接调用，保证与用法文案的 <QQ号|@用户> 一致；
            # 懒加载避免与 command.py 的模块级循环导入
            from Undefined.services.command import _normalize_qq_arg

            target_qqs = [int(_normalize_qq_arg(arg)) for arg in args[:-2]]
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
        """利用 AI 生成聊天记录的 Bug 分析摘要"""
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
                results.append(msg)
        return sorted(results, key=lambda m: m.get("time", 0))

    async def _process_messages(self, messages: list[dict[str, Any]]) -> str:
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
