from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from Undefined.attachments import AttachmentRegistry
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
        models_image_edit=SimpleNamespace(
            api_url="https://edit.example.com",
            api_key="sk-edit",
            model_name="grok-edit-1.0",
            request_params={},
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
            "delivery": "send",
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
            "delivery": "send",
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": lambda *_args, **_kwargs: None},
    )

    assert "size 无效" in result
    assert "1024x1024" in result


@pytest.mark.asyncio
async def test_execute_models_defaults_response_format_to_base64(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(request_params={}),
    )
    monkeypatch.setattr("Undefined.utils.paths.IMAGE_CACHE_DIR", tmp_path)

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")
    seen_request: dict[str, Any] = {}

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        seen_request["method"] = method
        seen_request["url"] = url
        seen_request["json_data"] = kwargs.get("json_data")
        return _FakeResponse()

    async def _send_image(
        target_id: int | str,
        message_type: str,
        file_path: str,
    ) -> None:
        _ = target_id, message_type, file_path

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1024x1024",
            "delivery": "send",
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": _send_image},
    )

    assert result == "AI 绘图已发送给 group 10001"
    assert seen_request["json_data"]["response_format"] == "base64"


@pytest.mark.asyncio
async def test_execute_models_reports_upstream_http_error_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(),
    )

    request = httpx.Request("POST", "https://image.example.com/v1/images/generations")
    response = httpx.Response(
        503,
        request=request,
        json={
            "error": {
                "code": "upstream_error",
                "message": "Image generation blocked or no valid final image",
            }
        },
    )

    async def _fake_request_with_retry(*_args: Any, **_kwargs: Any) -> Any:
        raise httpx.HTTPStatusError("boom", request=request, response=response)

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1024x1024",
            "delivery": "send",
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": lambda *_args, **_kwargs: None},
    )

    assert "HTTP 503" in result
    assert "upstream_error" in result
    assert "Image generation blocked or no valid final image" in result


@pytest.mark.asyncio
async def test_execute_blocks_when_agent_moderation_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(),
    )

    async def _fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("image generation request should not be sent")

    fake_ai_client = SimpleNamespace(
        agent_config=SimpleNamespace(model_name="agent-model"),
        request_model=AsyncMock(
            return_value={
                "choices": [
                    {"message": {"content": "BLOCK: 露骨色情内容"}},
                ]
            }
        ),
    )

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fail_if_called)

    result = await ai_draw_handler.execute(
        {
            "prompt": "explicit adult scene",
            "delivery": "send",
            "target_id": 10001,
            "message_type": "group",
        },
        {
            "ai_client": fake_ai_client,
            "send_image_callback": lambda *_args, **_kwargs: None,
        },
    )

    assert result == "图片生成请求被审核拦截：露骨色情内容"
    fake_ai_client.request_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_models_uses_configured_model_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(),
    )
    monkeypatch.setattr("Undefined.utils.paths.IMAGE_CACHE_DIR", tmp_path)

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")
    seen_request: dict[str, Any] = {}

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        seen_request["method"] = method
        seen_request["url"] = url
        seen_request["json_data"] = kwargs.get("json_data")
        return _FakeResponse()

    async def _send_image(
        target_id: int | str,
        message_type: str,
        file_path: str,
    ) -> None:
        _ = target_id, message_type, file_path

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "model": "dall-e-3",
            "size": "1024x1024",
            "delivery": "send",
            "target_id": 10001,
            "message_type": "group",
        },
        {"send_image_callback": _send_image},
    )

    assert result == "AI 绘图已发送给 group 10001"
    assert seen_request["json_data"]["model"] == "grok-imagine-1.0"


@pytest.mark.asyncio
async def test_execute_defaults_to_embed_and_returns_pic_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(request_params={}),
    )

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(*_args: Any, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse()

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1024x1024",
        },
        {
            "attachment_registry": registry,
            "request_type": "group",
            "group_id": 10001,
        },
    )

    assert result.startswith('已生成图片，可在回复中插入 <pic uid="pic_')
    uid = result.split('uid="', 1)[1].split('"', 1)[0]
    record = registry.resolve(uid, "group:10001")
    assert record is not None
    assert Path(str(record.local_path)).read_bytes() == _PNG_BYTES


@pytest.mark.asyncio
async def test_execute_send_infers_current_group_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(request_params={}),
    )

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(*_args: Any, **_kwargs: Any) -> _FakeResponse:
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

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    result = await ai_draw_handler.execute(
        {
            "prompt": "violet flowers",
            "size": "1024x1024",
            "delivery": "send",
        },
        {
            "attachment_registry": registry,
            "request_type": "group",
            "group_id": 10001,
            "send_image_callback": _send_image,
        },
    )

    assert result == "AI 绘图已发送给 group 10001"
    assert sent["target_id"] == 10001
    assert sent["message_type"] == "group"
    assert Path(sent["file_path"]).read_bytes() == _PNG_BYTES


@pytest.mark.asyncio
async def test_execute_models_reference_images_uses_edit_endpoint_and_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_config = _make_runtime_config(request_params={})
    runtime_config.models_image_edit.request_params = {"background": "transparent"}
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: runtime_config,
    )

    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")
    seen_request: dict[str, Any] = {}

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        seen_request["method"] = method
        seen_request["url"] = url
        seen_request["data"] = kwargs.get("data")
        seen_request["files"] = kwargs.get("files")
        return _FakeResponse()

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "group:10001",
        _PNG_BYTES,
        kind="image",
        display_name="ref.png",
        source_kind="test",
    )

    result = await ai_draw_handler.execute(
        {
            "prompt": "use this as reference",
            "size": "1024x1024",
            "reference_image_uids": [record.uid],
        },
        {
            "attachment_registry": registry,
            "request_type": "group",
            "group_id": 10001,
        },
    )

    assert result.startswith('已生成图片，可在回复中插入 <pic uid="pic_')
    assert seen_request["method"] == "POST"
    assert seen_request["url"] == "https://edit.example.com/v1/images/edits"
    assert seen_request["data"]["model"] == "grok-edit-1.0"
    assert seen_request["data"]["background"] == "transparent"
    assert len(seen_request["files"]) == 1
    assert seen_request["files"][0][0] == "image"
    assert isinstance(seen_request["files"][0][1][1], bytes)
    assert seen_request["files"][0][1][1] == _PNG_BYTES


@pytest.mark.asyncio
async def test_call_openai_models_edit_uses_retry_safe_byte_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload_base64 = base64.b64encode(_PNG_BYTES).decode("ascii")
    reference_path = tmp_path / "reference.png"
    reference_path.write_bytes(_PNG_BYTES)

    class _FakeResponse:
        text = ""

        def json(self) -> dict[str, Any]:
            return {"data": [{"base64": payload_base64}]}

    async def _fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        assert method == "POST"
        assert url == "https://edit.example.com/v1/images/edits"
        files = kwargs["files"]
        assert len(files) == 1
        filename, payload, content_type = files[0][1]
        assert filename == "reference.png"
        assert payload == _PNG_BYTES
        assert isinstance(payload, bytes)
        assert content_type == "image/png"
        return _FakeResponse()

    monkeypatch.setattr(ai_draw_handler, "request_with_retry", _fake_request_with_retry)

    result = await ai_draw_handler._call_openai_models_edit(
        prompt="use this as reference",
        api_url="https://edit.example.com",
        api_key="sk-edit",
        model_name="grok-edit-1.0",
        size="1024x1024",
        quality="",
        style="",
        response_format="base64",
        n=None,
        timeout_val=30.0,
        reference_image_paths=[reference_path],
        extra_params={},
        context={},
    )

    assert isinstance(result, ai_draw_handler._GeneratedImagePayload)
    assert result.image_bytes == _PNG_BYTES


@pytest.mark.asyncio
async def test_execute_models_reference_images_rejects_non_image_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "Undefined.config.get_config",
        lambda strict=False: _make_runtime_config(request_params={}),
    )

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "group:10001",
        b"hello",
        kind="file",
        display_name="demo.txt",
        source_kind="test",
    )

    result = await ai_draw_handler.execute(
        {
            "prompt": "use this as reference",
            "reference_image_uids": [record.uid],
        },
        {
            "attachment_registry": registry,
            "request_type": "group",
            "group_id": 10001,
        },
    )

    assert result == f"参考图 UID 不是图片：{record.uid}"
