"""Regression coverage for Runtime API application construction."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer, webchat_store
from Undefined.api.app import RUNTIME_API_CONTEXT_APP_KEY


@pytest.mark.filterwarnings("error::aiohttp.web_exceptions.NotAppKeyWarning")
def test_application_preserves_context_without_app_key_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webchat_store, "WEBCHAT_CONVERSATIONS_DIR", tmp_path)
    context = RuntimeAPIContext(
        config_getter=SimpleNamespace,
        onebot=None,
        ai=None,
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=0)

    app = server._create_app()

    assert app[RUNTIME_API_CONTEXT_APP_KEY] is context
