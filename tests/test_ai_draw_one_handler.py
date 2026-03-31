from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.skills.agents.entertainment_agent.tools.ai_draw_one import (
    handler as ai_draw_handler,
)


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_runtime_config(*, request_params: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(
        image_gen=SimpleNamespace(
            provider="models",
            openai_size="",
            openai_quality="",
            openai_style="",
            openai_timeout=120.0,
        ),
        models_image_gen=SimpleNamespace(
            api_url="https://image.example.com",
            api_key="sk-image",
            model_name="grok-imagine-1.0",
            request_params=request_params or {},
        ),
        chat_model=SimpleNamespace(
            api_url="https://chat.example.com",
            api_key="sk-chat",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("response_key", ["b64_json", "base64"])
async def test_execute_models_supports_base64_response_and_preserves_explicit_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    response_key: str,
) -> None:
    runtime_config = _make_runtime_config(
        request_params={
            "size": "1792x1024",
            "response_format": "url",
        }
    )
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: runtime_config,
    )
    monkeypatch.setattr("Undefined.utils.paths.IMAGE_CACHE_DIR", tmp_path)

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")
    seen_request: dict[str, Any] = {}
    request_count = 0

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{response_key: payload_base64}]}

    async def _fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        nonlocal request_count
        request_count += 1
        seen_request["method"] = method
        seen_request["url"] = url
        seen_request["json_data"] = kwargs.get("json_data")
        return _FakeResponse()

    sent: dict[str, Any] = {}

    async def _send_image(
        target_id: int | str,
        message_type: str,
        file_path: str,
    ) -> None:
        sent["target_id"] = target_id
        sent["message_type"] = message_type
        sent["file_path"] = file_path

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1024x1024",
            "response_format": response_key,
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": _send_image},
    )

    assert result == "AI 绘图已发送给 group 10001"
    assert request_count == 1
    assert seen_request["method"] == "POST"
    assert seen_request["json_data"]["size"] == "1024x1024"
    assert seen_request["json_data"]["response_format"] == response_key
    assert Path(sent["file_path"]).read_bytes() == _PNG_BYTES


@pytest.mark.asyncio
async def test_execute_models_rejects_invalid_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(),
    )

    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1:1",
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": lambda *_args, **_kwargs: None},
    )

    assert "size 无效" in result
    assert "1024x1024" in result
