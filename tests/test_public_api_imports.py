"""根包公共 API 与向后兼容 import 路径测试（Phase 3 API-FACADE 启用）。"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

# 根包 lazy re-export 符号（见 docs/python-api.md）
_ROOT_EXPORTS: tuple[str, ...] = (
    "Config",
    "get_config",
    "set_config",
    "AIClient",
    "ToolRegistry",
    "AgentRegistry",
    "PipelineRegistry",
    "BaseRegistry",
    "AnthropicSkillRegistry",
    "CognitiveService",
    "KnowledgeManager",
    "MemeService",
    "AttachmentRegistry",
    "RuntimeAPIServer",
    "RuntimeAPIContext",
)

# 拆分后须继续可用的 shim / 深层 import 路径
_BACKWARD_COMPAT_PATHS: tuple[tuple[str, str], ...] = (
    ("Undefined.config.loader", "Config"),
    ("Undefined.ai.client", "AIClient"),
    ("Undefined.attachments", "AttachmentRegistry"),
    ("Undefined.handlers", "MessageHandler"),
    ("Undefined.onebot", "OneBotClient"),
    ("Undefined.skills.tools", "ToolRegistry"),
    ("Undefined.skills.agents", "AgentRegistry"),
    ("Undefined.skills.pipelines.registry", "PipelineRegistry"),
    ("Undefined.skills.registry", "BaseRegistry"),
    ("Undefined.skills.anthropic_skills", "AnthropicSkillRegistry"),
    ("Undefined.cognitive.service", "CognitiveService"),
    ("Undefined.knowledge.manager", "KnowledgeManager"),
    ("Undefined.memes.service", "MemeService"),
    ("Undefined.api.app", "RuntimeAPIServer"),
    ("Undefined.api._context", "RuntimeAPIContext"),
)


@pytest.mark.parametrize("symbol", _ROOT_EXPORTS)
def test_root_package_exports(symbol: str) -> None:
    import Undefined

    assert hasattr(Undefined, symbol), f"Undefined.{symbol} missing from root exports"
    getattr(Undefined, symbol)


def test_root_package_all_matches_exports() -> None:
    import Undefined

    expected = {"__version__", *_ROOT_EXPORTS}
    assert set(Undefined.__all__) == expected


def test_root_package_lazy_import_does_not_load_cli_modules() -> None:
    import sys

    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "Undefined" or name.startswith("Undefined.")
    }
    try:
        for name in saved_modules:
            del sys.modules[name]

        import Undefined  # noqa: F401

        assert "Undefined.onebot" not in sys.modules
        assert "Undefined.handlers" not in sys.modules
        assert "Undefined.main" not in sys.modules
    finally:
        for name in list(sys.modules):
            if (
                name == "Undefined" or name.startswith("Undefined.")
            ) and name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)


@pytest.mark.parametrize(("module_path", "symbol"), _BACKWARD_COMPAT_PATHS)
def test_backward_compat_import_path(module_path: str, symbol: str) -> None:
    module = importlib.import_module(module_path)
    assert hasattr(module, symbol), f"{module_path}.{symbol} missing"
    getattr(module, symbol)


def test_set_config_not_used_by_default_get_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """库嵌入 set_config() 与 CLI get_config() 路径隔离（CONFIG Phase 2）。"""
    import Undefined.config as config_module

    from Undefined.config import Config, set_config

    config_module._config = None
    config_module._config_manager = None

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(
        """
[onebot]
ws_url = "ws://127.0.0.1:3999"
[models.chat]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "from-file"
""",
        encoding="utf-8",
    )

    cfg = config_module.get_config(strict=False)
    assert cfg.chat_model.model_name == "from-file"

    injected = Config.from_mapping(
        {
            "onebot": {"ws_url": "ws://127.0.0.1:3001"},
            "models": {
                "chat": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "injected",
                },
                "vision": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "vision-test",
                },
                "agent": {
                    "api_url": "https://api.example/v1",
                    "api_key": "sk-test",
                    "model_name": "agent-test",
                },
            },
        },
        strict=False,
    )
    set_config(injected)
    assert config_module.get_config(strict=False) is injected
