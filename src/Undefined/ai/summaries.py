"""Summary generation helpers."""

from __future__ import annotations

import logging

import aiofiles

from Undefined.ai.http import ModelRequester
from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.tokens import TokenCounter
from Undefined.config import ChatModelConfig

logger = logging.getLogger(__name__)


class SummaryService:
    def __init__(
        self,
        requester: ModelRequester,
        chat_config: ChatModelConfig,
        token_counter: TokenCounter,
        summarize_prompt_path: str = "res/prompts/summarize.txt",
        merge_prompt_path: str = "res/prompts/merge_summaries.txt",
    ) -> None:
        self._requester = requester
        self._chat_config = chat_config
        self._token_counter = token_counter
        self._summarize_prompt_path = summarize_prompt_path
        self._merge_prompt_path = merge_prompt_path

    async def summarize_chat(self, messages: str, context: str = "") -> str:
        async with aiofiles.open(
            self._summarize_prompt_path, "r", encoding="utf-8"
        ) as f:
            system_prompt = await f.read()

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
            return content
        except Exception as exc:
            logger.exception(f"[总结] 聊天记录总结失败: {exc}")
            return f"总结失败: {exc}"

    async def merge_summaries(self, summaries: list[str]) -> str:
        if len(summaries) == 1:
            return summaries[0]

        segments = [f"分段 {i + 1}:\n{s}" for i, s in enumerate(summaries)]
        segments_text = "---".join(segments)

        async with aiofiles.open(self._merge_prompt_path, "r", encoding="utf-8") as f:
            prompt = await f.read()
        prompt += segments_text

        try:
            result = await self._requester.request(
                model_config=self._chat_config,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=8192,
                call_type="merge_summaries",
            )
            content = extract_choices_content(result)
            return content
        except Exception as exc:
            logger.exception(f"合并总结失败: {exc}")
            return "\n\n---\n\n".join(summaries)

    def split_messages_by_tokens(self, messages: str, max_tokens: int) -> list[str]:
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
        prompt = (
            "请根据以下 Bug 修复分析报告，生成一个简短、准确的标题（不超过 20 字），用于 FAQ 索引。\n"
            "只返回标题文本，不要包含任何前缀或引号。\n\n"
            "分析报告：\n" + summary[:2000]
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
