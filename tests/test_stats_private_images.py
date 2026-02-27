from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.services.command import CommandDispatcher


@pytest.mark.asyncio
async def test_build_private_stats_image_message_uses_base64_when_requested(
    tmp_path: Path,
) -> None:
    dispatcher = object.__new__(CommandDispatcher)
    image = tmp_path / "stats.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    message = await dispatcher._build_private_stats_image_message(
        image,
        inline_base64=True,
    )

    assert message.startswith("[CQ:image,file=base64://")
    assert message.endswith("]")


@pytest.mark.asyncio
async def test_build_private_stats_image_message_uses_path_for_normal_private(
    tmp_path: Path,
) -> None:
    dispatcher = object.__new__(CommandDispatcher)
    image = tmp_path / "stats.png"
    image.write_bytes(b"fake")

    message = await dispatcher._build_private_stats_image_message(
        image,
        inline_base64=False,
    )

    assert message == f"[CQ:image,file={image.absolute().as_uri()}]"
