"""Token counting utilities."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TokenCounter:
    """Token counter with tiktoken fallback."""

    def __init__(self, model_name: str = "gpt-4") -> None:
        """初始化 Token 计数器

        参数:
            model_name: 使用的模型名称，用于获取对应的编码器
        """
        self._model_name = model_name
        self._tokenizer: Any | None = None
        self._try_load_tokenizer()

    def _try_load_tokenizer(self) -> None:
        """尝试加载适合指定模型的 tiktoken 编码器"""
        try:
            import tiktoken

            self._tokenizer = tiktoken.encoding_for_model(self._model_name)
            logger.info("[tokenizer] tiktoken 加载成功")
            return
        except Exception as exc:
            logger.warning(f"[tokenizer] tiktoken 加载失败，尝试回退到 GPT 编码: {exc}")

        try:
            import tiktoken

            self._tokenizer = tiktoken.encoding_for_model("gpt-4")
            logger.info("[tokenizer] 使用 GPT 编码回退成功")
            return
        except Exception as exc:
            logger.warning(f"[tokenizer] GPT 编码回退失败，尝试 cl100k_base: {exc}")

        try:
            import tiktoken

            self._tokenizer = tiktoken.get_encoding("cl100k_base")
            logger.info("[tokenizer] 使用 cl100k_base 回退成功")
            return
        except Exception as exc:
            self._tokenizer = None
            logger.warning(f"[tokenizer] 编码回退失败，将使用字符估算: {exc}")

    def count(self, text: str) -> int:
        """计算文本的 token 数量。"""
        if self._tokenizer is not None:
            return len(self._tokenizer.encode(text))
        # 后备方案：平均每 3 个字符算 1 个 token
        return len(text) // 3 + 1
