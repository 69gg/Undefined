"""CLI 启动兼容性与根包 import 行为测试（Phase 0 起持续有效）。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

import pytest

_MINIMAL_CONFIG = """
[onebot]
ws_url = "ws://127.0.0.1:3999"
[models.chat]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "gpt-test"
"""


@pytest.fixture
def isolated_undefined_modules() -> Iterator[None]:
    """测试前后清理 Undefined 相关 sys.modules 条目。"""
    prefix = "Undefined"
    saved = {
        k: v
        for k, v in sys.modules.items()
        if k == prefix or k.startswith(f"{prefix}.")
    }
    for key in saved:
        del sys.modules[key]
    yield
    for key in list(sys.modules):
        if key == prefix or key.startswith(f"{prefix}."):
            del sys.modules[key]
    sys.modules.update(saved)


@pytest.fixture
def reset_config_singleton() -> Iterator[None]:
    """重置 config 模块全局单例，避免测试间污染。"""
    import Undefined.config as config_module

    saved_config = config_module._config
    saved_manager = config_module._config_manager
    config_module._config = None
    config_module._config_manager = None
    yield
    config_module._config = saved_config
    config_module._config_manager = saved_manager


def test_entry_point_undefined_main_run_importable() -> None:
    from Undefined.main import run

    assert callable(run)


def test_entry_point_undefined_webui_run_importable() -> None:
    from Undefined.webui import run

    assert callable(run)


def test_import_undefined_does_not_eagerly_load_onebot_or_handlers(
    isolated_undefined_modules: None,
) -> None:
    import Undefined  # noqa: F401

    assert "Undefined.onebot" not in sys.modules
    assert "Undefined.handlers" not in sys.modules
    assert "Undefined.main" not in sys.modules


def test_get_config_reads_config_toml_from_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reset_config_singleton: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text(_MINIMAL_CONFIG, encoding="utf-8")

    import Undefined.config as config_module

    config_module._config = None
    config_module._config_manager = None

    cfg = config_module.get_config(strict=False)
    assert cfg.onebot_ws_url == "ws://127.0.0.1:3999"
    assert cfg.chat_model.model_name == "gpt-test"


def test_root_get_config_same_as_subpackage(isolated_undefined_modules: None) -> None:
    import Undefined

    from Undefined.config import get_config as subpackage_get_config

    assert Undefined.get_config is subpackage_get_config


def test_import_undefined_does_not_import_webui_app(
    isolated_undefined_modules: None,
) -> None:
    import Undefined  # noqa: F401

    assert "Undefined.webui.app" not in sys.modules


def test_webui_run_deferred_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """webui.run 应延迟加载 app，import webui 包本身不拉起重型依赖。"""
    import Undefined.webui as webui_module

    original_import = importlib.import_module
    app_imported = False

    def tracking_import(name: str, package: object | None = None) -> object:
        nonlocal app_imported
        if name == "Undefined.webui.app":
            app_imported = True
        package_name = package if isinstance(package, str) else None
        return original_import(name, package_name)

    monkeypatch.setattr(importlib, "import_module", tracking_import)
    importlib.reload(webui_module)

    assert not app_imported
    assert callable(webui_module.run)
