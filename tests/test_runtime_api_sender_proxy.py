from __future__ import annotations

import pytest

from Undefined.api.app import _WebUIVirtualSender


@pytest.mark.asyncio
async def test_webui_virtual_sender_redirects_private_and_group_messages() -> None:
    captured: list[tuple[int, str]] = []

    async def _capture(user_id: int, message: str) -> None:
        captured.append((user_id, message))

    sender = _WebUIVirtualSender(
        virtual_user_id=42,
        send_private_callback=_capture,
        onebot=object(),
    )

    await sender.send_private_message(123456, "hello private")
    await sender.send_group_message(654321, "hello group")

    assert captured == [
        (42, "hello private"),
        (42, "hello group"),
    ]
    assert sender.onebot is not None
