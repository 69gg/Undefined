"""知识库重排配置解析测试。"""

from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_knowledge_rerank_top_k_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[knowledge]
default_top_k = 5
enable_rerank = true
rerank_top_k = 9
""",
    )
    assert cfg.knowledge_enable_rerank is True
    assert cfg.knowledge_rerank_top_k == 4


def test_knowledge_rerank_auto_disabled_when_default_top_k_too_small(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[knowledge]
default_top_k = 1
enable_rerank = true
rerank_top_k = 1
""",
    )
    assert cfg.knowledge_enable_rerank is False


def test_rerank_query_instruction_loaded(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-test"
model_name = "text-rerank-001"
query_instruction = "Instruct: 检索相关文档\\nQuery: "
""",
    )
    assert cfg.rerank_model.query_instruction.startswith("Instruct:")
