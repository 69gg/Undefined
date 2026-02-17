"""Summary generation helpers."""

from __future__ import annotations

import logging

import aiofiles

from Undefined.ai.llm import ModelRequester
from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.tokens import TokenCounter
from Undefined.config import ChatModelConfig
from Undefined.utils.logging import log_debug_json
from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)


class SummaryService:
    def __init__(
        self,
        requester: ModelRequester,
        chat_config: ChatModelConfig,
        token_counter: TokenCounter,
        summarize_prompt_path: str = "res/prompts/summarize.txt",
        merge_prompt_path: str = "res/prompts/merge_summaries.txt",
        title_prompt_path: str = "res/prompts/generate_title.txt",
    ) -> None:
        self._requester = requester
        self._chat_config = chat_config
        self._token_counter = token_counter
        self._summarize_prompt_path = summarize_prompt_path
        self._merge_prompt_path = merge_prompt_path
        self._title_prompt_path = title_prompt_path

    async def summarize_chat(self, messages: str, context: str = "") -> str:
        """对聊天记录进行总结

        参数:
            messages: 待总结的聊天记录文本
            context: 前文摘要背景信息 (可选)

        返回:
            总结出的文本内容
        """
        try:
            system_prompt = read_text_resource(self._summarize_prompt_path)
        except Exception:
            async with aiofiles.open(
                self._summarize_prompt_path, "r", encoding="utf-8"
            ) as f:
                system_prompt = await f.read()
        logger.debug(
            "[总结] summarize_prompt_len=%s path=%s",
            len(system_prompt),
            self._summarize_prompt_path,
        )

        user_message = messages
        if context:
            user_message = f"前文摘要：\n{context}\n\n当前对话记录：\n{messages}"

        try:
            result = await self._requester.request(
                model_config=self._chat_config,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=8192,
                call_type="summarize",
            )
            content = extract_choices_content(result)
            logger.info(f"[总结] 生成完成, length={len(content)}")
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[总结] 输出内容", content)
            return content
        except Exception as exc:
            logger.exception(f"[总结] 聊天记录总结失败: {exc}")
            return f"总结失败: {exc}"

    async def merge_summaries(self, summaries: list[str]) -> str:
        """将多个分段总结整合为一个最终总结

        参数:
            summaries: 分段总结列表

        返回:
            合并后的最终总结
        """
        if len(summaries) == 1:
            return summaries[0]

        segments = [f"分段 {i + 1}:\n{s}" for i, s in enumerate(summaries)]
        segments_text = "---".join(segments)
        logger.debug(
            "[总结] merge_segments=%s total_len=%s", len(segments), len(segments_text)
        )

        try:
            prompt = read_text_resource(self._merge_prompt_path)
        except Exception:
            async with aiofiles.open(
                self._merge_prompt_path, "r", encoding="utf-8"
            ) as f:
                prompt = await f.read()
        logger.debug(
            "[总结] merge_prompt_len=%s path=%s",
            len(prompt),
            self._merge_prompt_path,
        )
        prompt += segments_text

        try:
            result = await self._requester.request(
                model_config=self._chat_config,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                call_type="merge_summaries",
            )
            content = extract_choices_content(result)
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[总结] 合并输出", content)
            return content
        except Exception as exc:
            logger.exception(f"合并总结失败: {exc}")
            return "\n\n---\n\n".join(summaries)

    def split_messages_by_tokens(self, messages: str, max_tokens: int) -> list[str]:
        """按 token 限制切分长消息

        参数:
            messages: 原始消息文本
            max_tokens: 最大允许的 token 数

        返回:
            切分后的消息段列表
        """
        effective_max = max_tokens - 500
        lines = messages.split("\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_tokens = 0

        for line in lines:
            line_tokens = self._token_counter.count(line)
            if current_tokens + line_tokens > effective_max and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            current_chunk.append(line)
            current_tokens += line_tokens

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    async def generate_title(self, summary: str) -> str:
        """根据总结内容生成标题

        参数:
            summary: 总结文本

        返回:
            生成的简短标题
        """
        summary_text = summary[:2000]
        prompt_template = (
            "请根据以下 Bug 修复分析报告，生成一个简短、准确的标题（不超过 20 字），用于 FAQ 索引。\n"
            "只返回标题文本，不要包含任何前缀或引号。\n\n"
            "分析报告：\n{summary}"
        )

        try:
            loaded_prompt_template = read_text_resource(self._title_prompt_path).strip()
            if loaded_prompt_template:
                prompt_template = loaded_prompt_template
        except Exception:
            try:
                async with aiofiles.open(
                    self._title_prompt_path, "r", encoding="utf-8"
                ) as f:
                    loaded_prompt_template = (await f.read()).strip()
                if loaded_prompt_template:
                    prompt_template = loaded_prompt_template
            except Exception:
                logger.debug(
                    "[总结] 标题提示词读取失败，使用内置模板: %s",
                    self._title_prompt_path,
                )

        try:
            prompt = prompt_template.format(summary=summary_text)
        except Exception:
            prompt = (
                "请根据以下 Bug 修复分析报告，生成一个简短、准确的标题（不超过 20 字），用于 FAQ 索引。\n"
                "只返回标题文本，不要包含任何前缀或引号。\n\n"
                "分析报告：\n" + summary_text
            )

        try:
            result = await self._requester.request(
                model_config=self._chat_config,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                call_type="generate_title",
            )
            title = extract_choices_content(result).strip()
            return title
        except Exception as exc:
            logger.exception(f"生成标题失败: {exc}")
            return "未命名问题"
