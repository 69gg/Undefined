"""Load knowledge config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_value,
)
from ..model_parsers import (
    _parse_embedding_model_config,
    _parse_rerank_model_config,
)

logger = logging.getLogger(__name__)


def load_knowledge(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    # 知识库段多数项仅读 TOML（env_key=None），避免与 embedding 模型 env 混淆
    embedding_model = _parse_embedding_model_config(data)
    rerank_model = _parse_rerank_model_config(data)

    knowledge_enabled = _coerce_bool(
        _get_value(data, ("knowledge", "enabled"), None), False
    )
    knowledge_base_dir = _coerce_str(
        _get_value(data, ("knowledge", "base_dir"), None), "knowledge"
    )
    knowledge_auto_scan = _coerce_bool(
        _get_value(data, ("knowledge", "auto_scan"), None), False
    )
    knowledge_auto_embed = _coerce_bool(
        _get_value(data, ("knowledge", "auto_embed"), None), False
    )
    knowledge_scan_interval = _coerce_float(
        _get_value(data, ("knowledge", "scan_interval"), None), 60.0
    )
    if knowledge_scan_interval <= 0:
        knowledge_scan_interval = 60.0
    knowledge_embed_batch_size = _coerce_int(
        _get_value(data, ("knowledge", "embed_batch_size"), None), 64
    )
    if knowledge_embed_batch_size <= 0:
        knowledge_embed_batch_size = 64
    knowledge_chunk_size = _coerce_int(
        _get_value(data, ("knowledge", "chunk_size"), None), 10
    )
    if knowledge_chunk_size <= 0:
        knowledge_chunk_size = 10
    knowledge_chunk_overlap = _coerce_int(
        _get_value(data, ("knowledge", "chunk_overlap"), None), 2
    )
    if knowledge_chunk_overlap < 0:
        knowledge_chunk_overlap = 0
    if knowledge_chunk_overlap >= knowledge_chunk_size:
        knowledge_chunk_overlap = max(0, knowledge_chunk_size - 1)
    knowledge_default_top_k = _coerce_int(
        _get_value(data, ("knowledge", "default_top_k"), None), 5
    )
    if knowledge_default_top_k <= 0:
        knowledge_default_top_k = 5
    knowledge_enable_rerank = _coerce_bool(
        _get_value(data, ("knowledge", "enable_rerank"), None), False
    )
    knowledge_rerank_top_k = _coerce_int(
        _get_value(data, ("knowledge", "rerank_top_k"), None), 3
    )
    if knowledge_rerank_top_k <= 0:
        knowledge_rerank_top_k = 3
    if knowledge_default_top_k <= 1 and knowledge_enable_rerank:
        logger.warning(
            "[配置] knowledge.default_top_k=%s，无法满足 rerank_top_k < default_top_k，"
            "已自动禁用重排",
            knowledge_default_top_k,
        )
        knowledge_enable_rerank = False
    if knowledge_rerank_top_k >= knowledge_default_top_k:
        fallback = knowledge_default_top_k - 1
        if fallback <= 0:
            fallback = 1
            knowledge_enable_rerank = False
            logger.warning(
                "[配置] knowledge.rerank_top_k 需小于 knowledge.default_top_k，"
                "且当前 default_top_k=%s 无法满足约束，已自动禁用重排",
                knowledge_default_top_k,
            )
        # 否则分支
        else:
            logger.warning(
                "[配置] knowledge.rerank_top_k 需小于 knowledge.default_top_k，"
                "已回退: rerank_top_k=%s -> %s (default_top_k=%s)",
                knowledge_rerank_top_k,
                fallback,
                knowledge_default_top_k,
            )
        knowledge_rerank_top_k = fallback

    return {
        "embedding_model": embedding_model,
        "rerank_model": rerank_model,
        "knowledge_enabled": knowledge_enabled,
        "knowledge_base_dir": knowledge_base_dir,
        "knowledge_auto_scan": knowledge_auto_scan,
        "knowledge_auto_embed": knowledge_auto_embed,
        "knowledge_scan_interval": knowledge_scan_interval,
        "knowledge_embed_batch_size": knowledge_embed_batch_size,
        "knowledge_chunk_size": knowledge_chunk_size,
        "knowledge_chunk_overlap": knowledge_chunk_overlap,
        "knowledge_default_top_k": knowledge_default_top_k,
        "knowledge_enable_rerank": knowledge_enable_rerank,
        "knowledge_rerank_top_k": knowledge_rerank_top_k,
    }
