"""Embedding model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any


from ..coercers import (
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_model_request_params,
    _get_value,
    _normalize_queue_interval,
)
from ..models import (
    EmbeddingModelConfig,
    RerankModelConfig,
)
from ..resolvers import (
    _resolve_context_window_tokens,
)

logger = logging.getLogger(__name__)


def _parse_embedding_model_config(data: dict[str, Any]) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        api_url=_coerce_str(
            _get_value(
                data, ("models", "embedding", "api_url"), "EMBEDDING_MODEL_API_URL"
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data, ("models", "embedding", "api_key"), "EMBEDDING_MODEL_API_KEY"
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data, ("models", "embedding", "model_name"), "EMBEDDING_MODEL_NAME"
            ),
            "",
        ),
        queue_interval_seconds=_normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data, ("models", "embedding", "queue_interval_seconds"), None
                ),
                0.0,
            ),
            0.0,
        ),
        dimensions=_coerce_int(
            _get_value(data, ("models", "embedding", "dimensions"), None), 0
        )
        or None,
        query_instruction=_coerce_str(
            _get_value(data, ("models", "embedding", "query_instruction"), None), ""
        ),
        context_window_tokens=_resolve_context_window_tokens(
            data, "embedding", "EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS"
        ),
        document_instruction=_coerce_str(
            _get_value(data, ("models", "embedding", "document_instruction"), None),
            "",
        ),
        request_params=_get_model_request_params(data, "embedding"),
    )


def _parse_rerank_model_config(data: dict[str, Any]) -> RerankModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(data, ("models", "rerank", "queue_interval_seconds"), None),
            0.0,
        ),
        0.0,
    )
    return RerankModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "rerank", "api_url"), "RERANK_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "rerank", "api_key"), "RERANK_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "rerank", "model_name"), "RERANK_MODEL_NAME"),
            "",
        ),
        queue_interval_seconds=queue_interval_seconds,
        context_window_tokens=_resolve_context_window_tokens(
            data, "rerank", "RERANK_MODEL_CONTEXT_WINDOW_TOKENS"
        ),
        query_instruction=_coerce_str(
            _get_value(data, ("models", "rerank", "query_instruction"), None), ""
        ),
        request_params=_get_model_request_params(data, "rerank"),
    )
