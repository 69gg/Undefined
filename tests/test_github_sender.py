from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.github.models import GitHubRepoInfo
import Undefined.github.sender as sender_module


def _repo_info() -> GitHubRepoInfo:
    return GitHubRepoInfo(
        repo_id="69gg/Undefined",
        name="Undefined",
        full_name="69gg/Undefined",
        owner_login="69gg",
        owner_avatar_url="https://avatars.githubusercontent.com/u/1?v=4",
        description="QQ bot platform",
        html_url="https://github.com/69gg/Undefined",
        stars=1234,
        forks=56,
        open_issues=7,
        watchers=1234,
        subscribers=89,
        contributors=42,
        language="Python",
        license_name="MIT",
        default_branch="main",
        topics=("bot", "onebot"),
        created_at="2024-01-02T03:04:05Z",
        updated_at="2026-05-01T03:04:05Z",
        pushed_at="2026-05-01T03:04:05Z",
        archived=False,
        fork=False,
    )


@pytest.mark.asyncio
async def test_send_github_repo_card_renders_and_sends_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rendered_html: list[str] = []

    async def fake_render_html_to_image(
        html_content: str,
        output_path: str,
        *,
        viewport_width: int = 1280,
        screenshot_selector: str | None = None,
        proxy: str | None = None,
    ) -> None:
        rendered_html.append(html_content)
        assert viewport_width == 768
        assert screenshot_selector == ".card"
        assert proxy is None
        Path(output_path).write_bytes(b"png")

    get_public_repo_info_mock = AsyncMock(return_value=_repo_info())
    avatar_data_url = "data:image/png;base64,YXZhdGFy"
    get_github_avatar_data_url_mock = AsyncMock(return_value=avatar_data_url)
    monkeypatch.setattr(
        sender_module, "get_public_repo_info", get_public_repo_info_mock
    )
    monkeypatch.setattr(
        sender_module,
        "get_github_avatar_data_url",
        get_github_avatar_data_url_mock,
    )
    monkeypatch.setattr(
        sender_module, "render_html_to_image", fake_render_html_to_image
    )
    monkeypatch.setattr(
        sender_module, "get_request_proxy", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(sender_module, "RENDER_CACHE_DIR", tmp_path)

    sender: Any = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )

    result = await sender_module.send_github_repo_card(
        repo_id="69gg/Undefined",
        sender=sender,
        target_type="group",
        target_id=10001,
        request_timeout=18.0,
        request_retries=4,
        context={"request_id": "sender-test"},
    )

    assert result == "已发送 GitHub 仓库卡片: 69gg/Undefined"
    get_public_repo_info_mock.assert_awaited_once_with(
        "69gg/Undefined",
        request_timeout=18.0,
        request_retries=4,
        context={"request_id": "sender-test"},
    )
    assert "69gg/Undefined" in rendered_html[0]
    assert "QQ bot platform" in rendered_html[0]
    assert "1,234" in rendered_html[0]
    assert avatar_data_url in rendered_html[0]
    assert "https://avatars.githubusercontent.com" not in rendered_html[0]
    get_github_avatar_data_url_mock.assert_awaited_once_with(
        "https://avatars.githubusercontent.com/u/1?v=4",
        request_timeout=18.0,
        request_retries=4,
        context={"request_id": "sender-test"},
    )
    sender.send_group_message.assert_called_once()
    sent_message = sender.send_group_message.call_args.args[1]
    assert sent_message.startswith("[CQ:image,file=file://")
    rendered_file = Path(
        sent_message.split("file=", 1)[1].rstrip("]").removeprefix("file://")
    )
    assert not rendered_file.exists()
    history_message = sender.send_group_message.call_args.kwargs["history_message"]
    assert history_message.startswith("GitHub: 69gg/Undefined")
    assert "auto_history" not in sender.send_group_message.call_args.kwargs


@pytest.mark.asyncio
async def test_load_owner_avatar_data_url_falls_back_to_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sender_module,
        "get_github_avatar_data_url",
        AsyncMock(side_effect=RuntimeError("download failed")),
    )

    avatar_data_url = await sender_module._load_owner_avatar_data_url(
        _repo_info(),
        request_timeout=10.0,
        request_retries=2,
        context=None,
    )
    html = sender_module._build_repo_card_html(
        _repo_info(),
        avatar_data_url=avatar_data_url,
    )

    assert avatar_data_url is None
    assert '<div class="avatar placeholder"></div>' in html
    assert "https://avatars.githubusercontent.com" not in html
