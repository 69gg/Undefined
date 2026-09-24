from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.config.loader import Config
from Undefined.config.models import (
    EMBEDDING_FEATURES,
    EmbeddingModelConfig,
    RerankModelConfig,
)
from Undefined.knowledge.runtime import RetrievalRuntimeRegistry

_BASE_TOML = """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.embedding]
api_url = "https://embed.example.com/v1"
api_key = "embed-key"
model_name = "default-embed"
use_proxy = true
context_window_tokens = 4096
queue_interval_seconds = 2.0
dimensions = 1024
query_instruction = "default-q: "
document_instruction = "default-d: "

[models.embedding.request_params]
encoding_format = "float"
"""


def _load_config(tmp_path: Path, extra: str = "") -> Config:
    path = tmp_path / "config.toml"
    path.write_text(_BASE_TOML + extra, "utf-8")
    return Config.load(path, strict=False)


class _DummyRequester:
    async def embed(
        self,
        _model_config: EmbeddingModelConfig,
        texts: list[str],
    ) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    async def rerank(
        self,
        _model_config: RerankModelConfig,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        return []


def test_features_absent_means_every_feature_inherits_default(tmp_path: Path) -> None:
    cfg = _load_config(tmp_path)
    assert cfg.embedding_features == {}
    for feature in EMBEDDING_FEATURES:
        assert cfg.resolve_embedding_model(feature) == cfg.embedding_model


def test_use_default_true_ignores_other_fields(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.cognitive]
use_default = true
model_name = "unused-embed"
dimensions = 3
query_instruction = "unused-q: "
""",
    )
    resolved = cfg.resolve_embedding_model("cognitive")
    assert resolved == cfg.embedding_model
    assert resolved.model_name == "default-embed"
    assert resolved.dimensions == 1024


def test_feature_overrides_individual_fields_and_keeps_rest(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.memes]
use_default = false
model_name = "meme-embed"
dimensions = 256
queue_interval_seconds = 0.5
query_instruction = "meme-q: "
""",
    )
    resolved = cfg.resolve_embedding_model("memes")

    assert resolved.model_name == "meme-embed"
    assert resolved.dimensions == 256
    assert resolved.queue_interval_seconds == 0.5
    assert resolved.query_instruction == "meme-q: "
    # 未覆写字段继续继承默认配置
    assert resolved.api_url == "https://embed.example.com/v1"
    assert resolved.api_key == "embed-key"
    assert resolved.use_proxy is True
    assert resolved.context_window_tokens == 4096
    assert resolved.document_instruction == "default-d: "
    assert resolved.request_params == {"encoding_format": "float"}


def test_feature_request_params_merge_over_defaults(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.knowledge]
use_default = false

[models.embedding.features.knowledge.request_params]
encoding_format = "base64"
user = "kb"
""",
    )
    resolved = cfg.resolve_embedding_model("knowledge")
    assert resolved.request_params == {
        "encoding_format": "base64",
        "user": "kb",
    }
    # 默认配置本身不受影响
    assert cfg.embedding_model.request_params == {"encoding_format": "float"}


def test_feature_use_proxy_tristate(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.knowledge]
use_default = false
use_proxy = false

[models.embedding.features.memes]
use_default = false
use_proxy = "inherit"

[models.embedding.features.cognitive]
use_default = false
use_proxy = true
""",
    )
    assert cfg.resolve_embedding_model("knowledge").use_proxy is False
    assert cfg.resolve_embedding_model("memes").use_proxy is True
    assert cfg.resolve_embedding_model("cognitive").use_proxy is True


def test_feature_dimension_sentinels(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.knowledge]
use_default = false
dimensions = 0

[models.embedding.features.cognitive]
use_default = false
dimensions = -1
""",
    )
    assert cfg.resolve_embedding_model("knowledge").dimensions is None
    assert cfg.resolve_embedding_model("cognitive").dimensions == 1024


def test_feature_context_window_and_interval_sentinels(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.knowledge]
use_default = false
context_window_tokens = 512
queue_interval_seconds = 0.0
""",
    )
    resolved = cfg.resolve_embedding_model("knowledge")
    assert resolved.context_window_tokens == 512
    assert resolved.queue_interval_seconds == 0.0


def test_instructions_preserve_whitespace(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.knowledge]
use_default = false
document_instruction = "passage: "
query_instruction = "Instruct: task\\nQuery: "

[models.rerank]
api_url = "https://embed.example.com/v1"
api_key = "rerank-key"
model_name = "rerank-model"
query_instruction = "Query: "
""",
    )
    resolved = cfg.resolve_embedding_model("knowledge")
    assert resolved.document_instruction == "passage: "
    assert resolved.query_instruction == "Instruct: task\nQuery: "
    assert cfg.rerank_model.query_instruction == "Query: "
    # 仅空白视为未设置
    assert cfg.embedding_model.document_instruction == "default-d: "


def test_unknown_feature_is_ignored(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path,
        """
[models.embedding.features.unknown_feature]
use_default = false
model_name = "nope"
""",
    )
    assert cfg.embedding_features == {}
    assert cfg.resolve_embedding_model("knowledge") == cfg.embedding_model


def test_runtime_registry_reuses_runtime_for_equal_configs() -> None:
    default = EmbeddingModelConfig(
        api_url="https://embed.example.com/v1",
        api_key="embed-key",
        model_name="default-embed",
    )
    registry = RetrievalRuntimeRegistry(
        _DummyRequester(),  # type: ignore[arg-type]
        embedding_models={feature: default for feature in EMBEDDING_FEATURES},
        rerank_model=RerankModelConfig(api_url="", api_key="", model_name=""),
    )

    knowledge_runtime = registry.for_feature("knowledge")
    cognitive_runtime = registry.for_feature("cognitive")

    assert knowledge_runtime is cognitive_runtime
    assert len(registry.runtimes) == 1
    assert registry.ensure_reranker() is None


@pytest.mark.asyncio
async def test_runtime_registry_splits_runtime_when_config_differs() -> None:
    default = EmbeddingModelConfig(
        api_url="https://embed.example.com/v1",
        api_key="embed-key",
        model_name="default-embed",
    )
    memes = EmbeddingModelConfig(
        api_url="https://embed.example.com/v1",
        api_key="embed-key",
        model_name="meme-embed",
        dimensions=256,
    )
    registry = RetrievalRuntimeRegistry(
        _DummyRequester(),  # type: ignore[arg-type]
        embedding_models={
            "knowledge": default,
            "cognitive": default,
            "memes": memes,
        },
        rerank_model=RerankModelConfig(
            api_url="https://embed.example.com/v1",
            api_key="rerank-key",
            model_name="rerank-model",
        ),
    )

    knowledge_runtime = registry.for_feature("knowledge")
    cognitive_runtime = registry.for_feature("cognitive")
    meme_runtime = registry.for_feature("memes")

    assert knowledge_runtime is cognitive_runtime
    assert meme_runtime is not knowledge_runtime
    assert len(registry.runtimes) == 2
    assert meme_runtime.embedding_model.model_name == "meme-embed"

    try:
        reranker = registry.ensure_reranker()
        assert reranker is not None
        # 重排在所有功能间共享同一个实例
        assert knowledge_runtime.ensure_reranker() is reranker
        assert meme_runtime.ensure_reranker() is reranker
    finally:
        await registry.stop()


def test_runtime_registry_unknown_feature() -> None:
    registry = RetrievalRuntimeRegistry(
        _DummyRequester(),  # type: ignore[arg-type]
        embedding_models={"knowledge": EmbeddingModelConfig("", "", "m")},
        rerank_model=RerankModelConfig(api_url="", api_key="", model_name=""),
    )
    with pytest.raises(KeyError):
        registry.for_feature("unknown")


def test_config_example_features_stay_in_sync_with_embedded_features() -> None:
    """config.toml.example 的 features 子表必须与 EMBEDDING_FEATURES 一一对应，
    防止新增 / 删除功能后示例漂移（未知功能名只会收到静默警告）。"""
    import tomllib

    example = (
        Path(__file__).resolve().parent.parent / "config.toml.example"
    ).read_text(encoding="utf-8")
    data = tomllib.loads(example)
    raw_features = data.get("models", {}).get("embedding", {}).get("features", {})
    documented = {
        name for name, value in raw_features.items() if isinstance(value, dict)
    }
    assert documented == set(EMBEDDING_FEATURES)
