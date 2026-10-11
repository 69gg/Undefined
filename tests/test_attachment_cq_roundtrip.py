"""CQ 参数从附件登记到最终 OneBot JSON 请求的无损往返。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.attachments import AttachmentRegistry, render_message_with_attachments
from Undefined.attachments import remote as attachment_remote
from Undefined.config import Config
from Undefined.onebot.client import OneBotClient
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.sender import MessageSender


class _RecordingWebSocket:
    close_code: int | None = None

    def __init__(self, client: OneBotClient) -> None:
        self.client = client
        self.requests: list[dict[str, Any]] = []

    async def send(self, payload: str) -> None:
        request = cast(dict[str, Any], json.loads(payload))
        self.requests.append(request)
        echo = str(request["echo"])
        self.client._pending_responses[echo].set_result(
            {"status": "ok", "retcode": 0, "data": {"message_id": 42}, "echo": echo}
        )


@pytest.mark.parametrize("target_type", ["group", "private"])
@pytest.mark.parametrize("mode", ["local", "url", "stream"])
@pytest.mark.parametrize(
    "source_url",
    [
        "https://8.8.8.8/image.png?crop=1,2",
        "https://8.8.8.8/image.png?list=[one,two]",
        "https://8.8.8.8/image.png?x=1&y=2",
        "https://8.8.8.8/image.png?literal=&#44;&#91;&#93;&amp;",
        "https://8.8.8.8/image.png?literal=[CQ:at,qq=12345]",
        "https://8.8.8.8/image.png?x=%2C%5B%5D%26&literal=&amp;#91;",
    ],
)
async def test_url_only_image_cq_preserves_source_and_metadata_on_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_url: str,
    target_type: str,
    mode: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    async def unexpected_dns(host: str, port: int) -> tuple[str, ...]:
        raise AssertionError(f"URL-only 登记不得触发 DNS: {host}:{port}")

    monkeypatch.setattr(attachment_remote, "resolve_host_addresses", unexpected_dns)
    registry_path = tmp_path / "registry.json"
    cache_dir = tmp_path / "attachments"
    registry = AttachmentRegistry(
        registry_path=registry_path,
        cache_dir=cache_dir,
        remote_download_max_bytes=0,
    )
    assert registry_path.is_relative_to(tmp_path)
    assert cache_dir.is_relative_to(tmp_path)
    scope = f"{target_type}:10001"
    summary = "a,b]&[&#44;&#91;&#93;&amp;"
    record = await registry.register_remote_url(
        scope,
        source_url,
        kind="image",
        display_name="remote.png",
        segment_data={"summary": summary, "subType": "1"},
    )
    assert record.local_path is None
    rendered = await render_message_with_attachments(
        f'前文 <attachment uid="{record.uid}"/> 后文',
        registry=registry,
        scope_key=scope,
        strict=True,
    )

    config = Config.from_mapping({"onebot": {"file_send_mode": mode}}, strict=False)
    onebot = OneBotClient("ws://unused.invalid", config_getter=lambda: config)
    onebot.file_transport.store.cache_dir = tmp_path / "onebot-files"
    assert onebot.file_transport.store.cache_dir.is_relative_to(tmp_path)
    websocket = _RecordingWebSocket(onebot)
    onebot.ws = cast(Any, websocket)
    history = MagicMock(spec=MessageHistoryManager)
    history.add_group_message = AsyncMock()
    history.add_private_message = AsyncMock()
    sender = MessageSender(
        onebot,
        history,
        bot_qq=20002,
        config=config,
        attachment_registry=registry,
    )
    if target_type == "group":
        result = await sender.send_group_message(
            10001,
            rendered.delivery_text,
            history_message=rendered.history_text,
            attachments=rendered.attachments,
        )
        history_call = history.add_group_message.await_args
    else:
        result = await sender.send_private_message(
            10001,
            rendered.delivery_text,
            history_message=rendered.history_text,
            attachments=rendered.attachments,
        )
        history_call = history.add_private_message.await_args

    assert result == 42
    assert len(websocket.requests) == 1
    request = websocket.requests[0]
    assert request["action"] == f"send_{target_type}_msg"
    assert request["params"]["message"] == [
        {"type": "text", "data": {"text": "前文 "}},
        {
            "type": "image",
            "data": {"file": source_url, "summary": summary, "subType": "1"},
        },
        {"type": "text", "data": {"text": " 后文"}},
    ]
    assert history_call is not None
    assert history_call.kwargs["attachments"] == rendered.attachments
    assert (await registry.resolve_async(record.uid, scope)) == record
    assert not onebot._pending_responses
    assert not onebot.file_transport.store.cache_dir.exists()
