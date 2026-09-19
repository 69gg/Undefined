"""Embedding model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any


from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_instruction,
    _coerce_int,
    _coerce_request_params,
    _coerce_str,
    _get_model_request_params,
    _get_value,
    _normalize_queue_interval,
)
from ..models import (
    EMBEDDING_FEATURES,
    EmbeddingFeatureOverride,
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
        use_proxy=_coerce_bool(
            _get_value(
                data,
                ("models", "embedding", "use_proxy"),
                "EMBEDDING_MODEL_USE_PROXY",
            ),
            False,
        ),
        queue_interval_seconds=_normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data, ("models", "embedding", "queue_interval_seconds"), None
                ),
                0.0,
            )
        ),
        dimensions=_coerce_int(
            _get_value(data, ("models", "embedding", "dimensions"), None), 0
        )
        or None,
        query_instruction=_coerce_instruction(
            _get_value(data, ("models", "embedding", "query_instruction"), None), ""
        ),
        context_window_tokens=_resolve_context_window_tokens(
            data, "embedding", "EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS"
        ),
        document_instruction=_coerce_instruction(
            _get_value(data, ("models", "embedding", "document_instruction"), None),
            "",
        ),
        request_params=_get_model_request_params(data, "embedding"),
    )


def _coerce_inheritable_bool(value: Any) -> bool | None:
    """解析三态布尔：``None`` / "inherit" / "default" 表示继承默认配置。"""
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {
        "inherit",
        "default",
        "unset",
        "",
    }:
        return None
    return _coerce_bool(value, False)


def _parse_embedding_feature_overrides(
    data: dict[str, Any],
) -> dict[str, EmbeddingFeatureOverride]:
    """解析 ``[models.embedding.features.<name>]`` 按功能覆写配置。"""
    raw = _get_value(data, ("models", "embedding", "features"), None)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        logger.warning(
            "[配置] models.embedding.features 必须是表，实际类型=%s，已忽略",
            type(raw).__name__,
        )
        return {}

    unknown = sorted(str(name) for name in raw if name not in EMBEDDING_FEATURES)
    if unknown:
        logger.warning(
            "[配置] models.embedding.features 中存在未知功能名，已忽略: %s",
            ", ".join(unknown),
        )

    overrides: dict[str, EmbeddingFeatureOverride] = {}
    for name in EMBEDDING_FEATURES:
        entry = raw.get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            logger.warning(
                "[配置] models.embedding.features.%s 必须是表，实际类型=%s，已忽略",
                name,
                type(entry).__name__,
            )
            continue
        overrides[name] = EmbeddingFeatureOverride(
            use_default=_coerce_bool(entry.get("use_default", True), True),
            api_url=_coerce_str(entry.get("api_url"), ""),
            api_key=_coerce_str(entry.get("api_key"), ""),
            model_name=_coerce_str(entry.get("model_name"), ""),
            use_proxy=_coerce_inheritable_bool(entry.get("use_proxy")),
            context_window_tokens=_coerce_int(entry.get("context_window_tokens"), 0),
            queue_interval_seconds=_coerce_float(
                entry.get("queue_interval_seconds"), -1.0
            ),
            dimensions=_coerce_int(entry.get("dimensions"), -1),
            query_instruction=_coerce_instruction(entry.get("query_instruction"), ""),
            document_instruction=_coerce_instruction(
                entry.get("document_instruction"), ""
            ),
            request_params=_coerce_request_params(entry.get("request_params")),
        )
    return overrides


def _parse_rerank_model_config(data: dict[str, Any]) -> RerankModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(data, ("models", "rerank", "queue_interval_seconds"), None),
            0.0,
        )
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
        use_proxy=_coerce_bool(
            _get_value(
                data, ("models", "rerank", "use_proxy"), "RERANK_MODEL_USE_PROXY"
            ),
            False,
        ),
        queue_interval_seconds=queue_interval_seconds,
        context_window_tokens=_resolve_context_window_tokens(
            data, "rerank", "RERANK_MODEL_CONTEXT_WINDOW_TOKENS"
        ),
        query_instruction=_coerce_instruction(
            _get_value(data, ("models", "rerank", "query_instruction"), None), ""
        ),
        request_params=_get_model_request_params(data, "rerank"),
    )
