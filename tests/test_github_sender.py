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

    monkeypatch.setattr(
        sender_module,
        "get_public_repo_info",
        AsyncMock(return_value=_repo_info()),
    )
    monkeypatch.setattr(
        sender_module, "render_html_to_image", fake_render_html_to_image
    )
    monkeypatch.setattr(sender_module, "get_request_proxy", lambda _url: None)
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
    )

    assert result == "已发送 GitHub 仓库卡片: 69gg/Undefined"
    assert "69gg/Undefined" in rendered_html[0]
    assert "QQ bot platform" in rendered_html[0]
    assert "1,234" in rendered_html[0]
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
