"""检索类请求封装（嵌入 / 重排）。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, TypeAlias

from openai import NOT_GIVEN, AsyncOpenAI

from Undefined.ai.tokens import TokenCounter
from Undefined.config import EmbeddingModelConfig, RerankModelConfig

logger = logging.getLogger(__name__)

_ModelConfig: TypeAlias = EmbeddingModelConfig | RerankModelConfig
_OpenAIClientGetter: TypeAlias = Callable[[_ModelConfig], AsyncOpenAI]
_ResponseToDict: TypeAlias = Callable[[Any], dict[str, Any]]
_TokenCounterGetter: TypeAlias = Callable[[str], TokenCounter]
_RecordUsageCallback: TypeAlias = Callable[..., None]


class RetrievalRequester:
    """统一处理嵌入与重排请求，便于复用统计与 SDK 调用逻辑。"""

    def __init__(
        self,
        *,
        get_openai_client: _OpenAIClientGetter,
        response_to_dict: _ResponseToDict,
        get_token_counter: _TokenCounterGetter,
        record_usage: _RecordUsageCallback,
    ) -> None:
        self._get_openai_client = get_openai_client
        self._response_to_dict = response_to_dict
        self._get_token_counter = get_token_counter
        self._record_usage = record_usage

    async def embed(
        self, model_config: EmbeddingModelConfig, texts: list[str]
    ) -> list[list[float]]:
        """调用 OpenAI 兼容 embeddings API。"""
        if not texts:
            return []

        start_time = time.perf_counter()
        client = self._get_openai_client(model_config)
        response = await client.embeddings.create(
            model=model_config.model_name,
            input=texts,
            dimensions=model_config.dimensions or NOT_GIVEN,  # type: ignore[arg-type]
        )
        response_dict = self._response_to_dict(response)
        embeddings = [item.embedding for item in response.data]
        duration = time.perf_counter() - start_time

        prompt_tokens, completion_tokens, total_tokens = self._extract_usage(
            response_dict
        )
        if total_tokens <= 0:
            prompt_tokens, completion_tokens, total_tokens = self._estimate_usage(
                model_name=model_config.model_name,
                prompt_text="\n".join(texts),
                completion_data=None,
            )

        self._record_usage(
            model_name=model_config.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_seconds=duration,
            call_type="embedding",
        )
        logger.info(
            "[API响应] embedding 完成: 耗时=%.2fs, Tokens=%s (P:%s + C:%s), 模型=%s",
            duration,
            total_tokens,
            prompt_tokens,
            completion_tokens,
            model_config.model_name,
        )
        return embeddings

    async def rerank(
        self,
        model_config: RerankModelConfig,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """调用 OpenAI 兼容 rerank API。"""
        if not documents:
            return []

        start_time = time.perf_counter()
        client = self._get_openai_client(model_config)
        request_body: dict[str, Any] = {
            "model": model_config.model_name,
            "query": query,
            "documents": documents,
            "return_documents": False,
        }
        query_instruction = str(getattr(model_config, "query_instruction", "") or "")
        if query_instruction:
            request_body["query"] = f"{query_instruction}{query}"
        if isinstance(top_n, int) and top_n > 0:
            request_body["top_n"] = top_n

        # Some OpenAI-compatible providers return non-dict JSON payloads for rerank.
        # Use a broad cast target and normalize the payload shape ourselves.
        response = await client.post(
            "/rerank",
            cast_to=object,
            body=request_body,
        )
        response_dict = self._normalize_rerank_payload(response)
        results = self._normalize_rerank_results(
            response_dict,
            documents=documents,
            top_n=top_n,
        )
        duration = time.perf_counter() - start_time

        prompt_tokens, completion_tokens, total_tokens = self._extract_usage(
            response_dict
        )
        if total_tokens <= 0:
            prompt_tokens, completion_tokens, total_tokens = self._estimate_usage(
                model_name=model_config.model_name,
                prompt_text=json.dumps(request_body, ensure_ascii=False, default=str),
                completion_data=results,
            )

        self._record_usage(
            model_name=model_config.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_seconds=duration,
            call_type="rerank",
        )
        logger.info(
            "[API响应] rerank 完成: 耗时=%.2fs, Tokens=%s (P:%s + C:%s), 模型=%s, docs=%s",
            duration,
            total_tokens,
            prompt_tokens,
            completion_tokens,
            model_config.model_name,
            len(documents),
        )
        return results

    def _normalize_rerank_payload(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        if isinstance(response, list):
            return {"data": response}
        if response is None:
            return {}
        converted = self._response_to_dict(response)
        if isinstance(converted, dict):
            return converted
        return {}

    def _extract_usage(self, response_dict: dict[str, Any]) -> tuple[int, int, int]:
        usage = response_dict.get("usage", {}) or {}
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = self._safe_int(
            usage.get("prompt_tokens", usage.get("input_tokens", 0))
        )
        completion_tokens = self._safe_int(
            usage.get("completion_tokens", usage.get("output_tokens", 0))
        )
        total_tokens = self._safe_int(usage.get("total_tokens", 0))
        if total_tokens <= 0 and (prompt_tokens > 0 or completion_tokens > 0):
            total_tokens = prompt_tokens + completion_tokens
        return prompt_tokens, completion_tokens, total_tokens

    def _estimate_usage(
        self,
        *,
        model_name: str,
        prompt_text: str,
        completion_data: Any,
    ) -> tuple[int, int, int]:
        counter = self._get_token_counter(model_name)
        prompt_tokens = counter.count(prompt_text) if prompt_text else 0
        completion_text = ""
        if completion_data is not None:
            try:
                completion_text = json.dumps(
                    completion_data, ensure_ascii=False, default=str
                )
            except Exception:
                completion_text = str(completion_data)
        completion_tokens = counter.count(completion_text) if completion_text else 0
        total_tokens = prompt_tokens + completion_tokens
        return prompt_tokens, completion_tokens, total_tokens

    def _normalize_rerank_results(
        self,
        payload: dict[str, Any],
        *,
        documents: list[str],
        top_n: int | None,
    ) -> list[dict[str, Any]]:
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            data = payload.get("data")
            if isinstance(data, list):
                raw_results = data
            else:
                raw_results = []

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_results):
            if not isinstance(item, dict):
                continue
            doc_index = self._safe_int(item.get("index", idx))
            if doc_index < 0:
                continue

            score_value = item.get(
                "relevance_score",
                item.get("score", item.get("similarity", 0.0)),
            )
            if isinstance(score_value, (int, float)):
                relevance_score = float(score_value)
            elif isinstance(score_value, str):
                try:
                    relevance_score = float(score_value)
                except ValueError:
                    relevance_score = 0.0
            else:
                relevance_score = 0.0

            document = item.get("document")
            if not isinstance(document, str):
                if doc_index < len(documents):
                    document = documents[doc_index]
                else:
                    document = ""

            normalized.append(
                {
                    "index": doc_index,
                    "relevance_score": relevance_score,
                    "document": document,
                }
            )

        if normalized:
            return normalized

        limit = len(documents)
        if isinstance(top_n, int) and top_n > 0:
            limit = min(limit, top_n)
        return [
            {
                "index": i,
                "relevance_score": 0.0,
                "document": documents[i],
            }
            for i in range(limit)
        ]

    def _safe_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
