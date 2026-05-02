from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.skills.toolsets.group.get_avatar.handler import execute as get_avatar
from Undefined.skills.toolsets.group.get_member_info.handler import (
    execute as get_member_info,
)


class _FakeOneBot:
    def __init__(self, member_info: dict[str, Any]) -> None:
        self.member_info = member_info
        self.calls: list[tuple[int, int, bool]] = []

    async def get_group_member_info(
        self,
        group_id: int,
        user_id: int,
        no_cache: bool,
    ) -> dict[str, Any]:
        self.calls.append((group_id, user_id, no_cache))
        return self.member_info


class _FakeAttachmentRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def register_remote_url(
        self,
        scope_key: str,
        url: str,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((scope_key, url, kwargs))
        return SimpleNamespace(uid="pic_avatar")


@pytest.mark.asyncio
async def test_get_member_info_brief_returns_only_display_name() -> None:
    onebot = _FakeOneBot({"card": "Alice", "nickname": "Fallback"})

    result = await get_member_info(
        {"group_id": 123456, "user_id": 1001, "brief": True},
        {"onebot_client": onebot},
    )

    assert result == "Alice"
    assert onebot.calls == [(123456, 1001, False)]


@pytest.mark.asyncio
async def test_get_member_info_brief_falls_back_to_nickname_or_user_id() -> None:
    nickname_onebot = _FakeOneBot({"card": "", "nickname": "Bob"})
    no_name_onebot = _FakeOneBot({"card": "", "nickname": ""})

    nickname_result = await get_member_info(
        {"group_id": 123456, "user_id": 1002, "brief": True},
        {"onebot_client": nickname_onebot},
    )
    no_name_result = await get_member_info(
        {"group_id": 123456, "user_id": 1003, "brief": True},
        {"onebot_client": no_name_onebot},
    )

    assert nickname_result == "Bob"
    assert no_name_result == "1003"


@pytest.mark.asyncio
async def test_get_avatar_accepts_string_size_and_returns_attachment_tag() -> None:
    registry = _FakeAttachmentRegistry()

    result = await get_avatar(
        {"user_id": "1001", "size": "640"},
        {"group_id": 123456, "attachment_registry": registry},
    )

    assert result == '<attachment uid="pic_avatar"/>'
    assert registry.calls
    scope_key, avatar_url, kwargs = registry.calls[0]
    assert scope_key == "group:123456"
    assert avatar_url == "https://q1.qlogo.cn/g?b=qq&nk=1001&s=3"
    assert kwargs["kind"] == "image"
    assert kwargs["display_name"] == "avatar_1001.jpg"
