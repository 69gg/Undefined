from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_script_module() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parent.parent / "scripts" / "sync_config_template.py"
    )
    spec = importlib.util.spec_from_file_location(
        "sync_config_template_script", script_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prune_mode_reports_analysis_before_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script_module()
    calls: list[tuple[bool, bool]] = []

    def fake_sync_config_file(
        *,
        config_path: Path,
        example_path: Path,
        write: bool = True,
        prune: bool = False,
    ) -> SimpleNamespace:
        del config_path, example_path
        calls.append((write, prune))
        return SimpleNamespace(
            content="",
            added_paths=[],
            removed_paths=["models.chat.extra"],
            comments={},
            updated_comment_paths=[],
        )

    monkeypatch.setattr(module, "sync_config_file", fake_sync_config_file)
    monkeypatch.setattr(module, "_confirm_prune", lambda _paths: False)
    monkeypatch.setattr(sys, "argv", ["sync_config_template.py", "--prune"])

    assert module.main() == 0

    output = capsys.readouterr().out
    assert "[sync-config] 分析完成:" in output
    assert calls == [(False, False), (True, False)]
