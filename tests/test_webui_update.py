from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Coroutine, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from Undefined.github.models import GitHubReleaseInfo
from Undefined.utils import io as async_io
from Undefined.utils.self_update import (
    GitUpdatePolicy,
    GitUpdateResult,
    apply_git_release_update,
)
from Undefined.webui.routes import _bot
from Undefined.webui.routes._shared import BOT_APP_KEY, SETTINGS_APP_KEY


class _DummyRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


def _request(
    *,
    check_updates: bool = True,
    manual: bool = False,
    json_body: dict[str, object] | None = None,
    bot: MagicMock | None = None,
) -> _DummyRequest:
    return _DummyRequest(
        query={"manual": "true"} if manual else {},
        app={
            SETTINGS_APP_KEY: SimpleNamespace(check_updates=check_updates),
            BOT_APP_KEY: bot or MagicMock(),
        },
        _json=json_body or {},
        can_read_body=json_body is not None,
    )


def _payload(response: web.StreamResponse) -> dict[str, object]:
    text = cast(web.Response, response).text
    assert text is not None
    return cast(dict[str, object], json.loads(text))


def _release(tag: str = "v3.8.0") -> GitHubReleaseInfo:
    return GitHubReleaseInfo(
        tag_name=tag,
        name=f"Undefined {tag}",
        html_url=f"https://github.com/69gg/Undefined/releases/tag/{tag}",
        published_at="2026-07-10T08:00:00Z",
        target_commitish="main",
        draft=False,
        prerelease=False,
    )


@pytest.fixture(autouse=True)
def _isolate_release_cache() -> Iterator[None]:
    _bot._reset_release_cache()
    yield
    _bot._reset_release_cache()


@pytest.fixture
def _authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_bot, "check_auth", lambda _request: True)


@pytest.mark.asyncio
async def test_automatic_update_check_respects_disabled_setting(
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    fetch_release = AsyncMock()
    monkeypatch.setattr(_bot, "_get_latest_release_cached", fetch_release)

    response = await _bot.update_check_handler(
        cast(web.Request, cast(Any, _request(check_updates=False)))
    )

    assert _payload(response) == {
        "success": True,
        "enabled": False,
        "checked": False,
        "update_available": False,
    }
    fetch_release.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_update_check_bypasses_disabled_setting(
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    async def fake_latest(
        _policy: object,
    ) -> tuple[GitHubReleaseInfo, bool]:
        return _release("v3.7.0"), False

    monkeypatch.setattr(_bot, "_get_latest_release_cached", fake_latest)
    monkeypatch.setattr(_bot, "__version__", "3.7.0")

    response = await _bot.update_check_handler(
        cast(
            web.Request,
            cast(Any, _request(check_updates=False, manual=True)),
        )
    )
    data = _payload(response)

    assert data["enabled"] is False
    assert data["checked"] is True
    assert data["update_available"] is False
    assert data["reason"] == "up_to_date"


@pytest.mark.asyncio
async def test_update_check_reports_new_release_and_git_ineligibility(
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    async def fake_latest(
        _policy: object,
    ) -> tuple[GitHubReleaseInfo, bool]:
        return _release(), True

    monkeypatch.setattr(_bot, "_get_latest_release_cached", fake_latest)
    monkeypatch.setattr(_bot, "__version__", "3.7.0")
    monkeypatch.setattr(
        _bot,
        "check_git_update_eligibility",
        lambda _policy: GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=Path("/repo"),
            reason="branch_mismatch",
            origin_url="https://github.com/69gg/Undefined.git",
            branch="feature/check-update",
        ),
    )

    response = await _bot.update_check_handler(cast(web.Request, cast(Any, _request())))
    data = _payload(response)

    assert data["current_version"] == "v3.7.0"
    assert data["latest_version"] == "v3.8.0"
    assert data["update_available"] is True
    assert data["eligible"] is False
    assert data["reason"] == "branch_mismatch"
    assert data["cached"] is True


@pytest.mark.asyncio
async def test_release_cache_collapses_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_get_latest_release(
        _repo_id: str,
        **_kwargs: Any,
    ) -> GitHubReleaseInfo:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return _release()

    monkeypatch.setattr(
        _bot,
        "get_config",
        lambda strict=False: SimpleNamespace(
            github_request_timeout_seconds=10.0,
            github_request_retries=2,
        ),
    )
    monkeypatch.setattr(
        _bot,
        "get_latest_public_release",
        fake_get_latest_release,
    )
    policy = GitUpdatePolicy()

    results = await asyncio.gather(
        _bot._get_latest_release_cached(policy),
        _bot._get_latest_release_cached(policy),
        _bot._get_latest_release_cached(policy),
    )

    assert calls == 1
    assert sum(1 for _release_info, cached in results if cached) == 2


@pytest.mark.asyncio
async def test_release_cache_collapses_concurrent_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    request_started = asyncio.Event()
    finish_request = asyncio.Event()

    async def fake_get_latest_release(
        _repo_id: str,
        **_kwargs: Any,
    ) -> GitHubReleaseInfo:
        nonlocal calls
        calls += 1
        request_started.set()
        await finish_request.wait()
        raise RuntimeError("GitHub unavailable")

    monkeypatch.setattr(
        _bot,
        "get_config",
        lambda strict=False: SimpleNamespace(
            github_request_timeout_seconds=10.0,
            github_request_retries=2,
        ),
    )
    monkeypatch.setattr(
        _bot,
        "get_latest_public_release",
        fake_get_latest_release,
    )
    policy = GitUpdatePolicy()
    requests = [
        asyncio.create_task(_bot._get_latest_release_cached(policy))
        for _index in range(3)
    ]

    await request_started.wait()
    finish_request.set()
    results = await asyncio.gather(*requests, return_exceptions=True)

    assert calls == 1
    assert all(
        isinstance(result, RuntimeError) and str(result) == "GitHub unavailable"
        for result in results
    )

    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        await _bot._get_latest_release_cached(policy)
    assert calls == 2


@pytest.mark.asyncio
async def test_update_restart_applies_confirmed_release_tag(
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    async def fake_release_payload(
        _policy: object,
    ) -> tuple[dict[str, object], None]:
        return (
            {
                "success": True,
                "checked": True,
                "current_version": "v3.7.0",
                "latest_version": "v3.8.0",
                "update_available": True,
                "release": {"name": "Undefined v3.8.0"},
                "cached": True,
            },
            None,
        )

    bot = MagicMock()
    bot.status.return_value = {"running": False}
    applied: dict[str, object] = {}

    def fake_apply(
        _policy: object,
        *,
        release_tag: str,
        start_dir: Path,
    ) -> GitUpdateResult:
        applied["release_tag"] = release_tag
        applied["start_dir"] = start_dir
        return GitUpdateResult(
            eligible=True,
            updated=True,
            repo_root=Path("/repo"),
            reason="updated",
            old_rev="a" * 40,
            new_rev="b" * 40,
            remote_rev="b" * 40,
            target_tag=release_tag,
        )

    created_coroutines: list[Coroutine[Any, Any, None]] = []
    created_task = MagicMock()
    created_task.done.return_value = False
    created_task.cancelled.return_value = False
    created_task.exception.return_value = None

    def fake_create_task(
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str | None = None,
    ) -> MagicMock:
        assert name == "webui-release-restart"
        created_coroutines.append(coroutine)
        coroutine.close()
        return created_task

    monkeypatch.setattr(_bot, "_load_release_payload", fake_release_payload)
    monkeypatch.setattr(
        _bot,
        "check_git_update_eligibility",
        lambda _policy: GitUpdateResult(
            eligible=True,
            updated=False,
            repo_root=Path("/repo"),
            reason="eligible",
        ),
    )
    monkeypatch.setattr(_bot, "apply_git_release_update", fake_apply)
    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    response = await _bot.update_restart_handler(
        cast(
            web.Request,
            cast(
                Any,
                _request(
                    json_body={"target_version": "v3.8.0"},
                    bot=bot,
                ),
            ),
        )
    )
    data = _payload(response)

    assert applied == {"release_tag": "v3.8.0", "start_dir": Path("/repo")}
    assert data["updated"] is True
    assert data["will_restart"] is True
    assert data["target_version"] == "v3.8.0"
    assert len(created_coroutines) == 1
    assert _bot._release_restart_task is created_task
    done_callback = created_task.add_done_callback.call_args.args[0]
    done_callback(created_task)
    assert _bot._release_restart_task is None


@pytest.mark.asyncio
async def test_update_restart_timeout_restores_bot_and_repo_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    async def fake_release_payload(
        _policy: object,
    ) -> tuple[dict[str, object], None]:
        return (
            {
                "success": True,
                "checked": True,
                "current_version": "v3.7.1",
                "latest_version": "v3.8.0",
                "update_available": True,
                "release": {"name": "Undefined v3.8.0"},
                "cached": True,
            },
            None,
        )

    async def slow_to_thread(
        function: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        assert function is apply_git_release_update
        assert kwargs["start_dir"] == tmp_path
        await asyncio.Event().wait()

    marker_paths: list[Path] = []

    async def track_marker_write(path: Path, content: str) -> None:
        assert content == "1"
        marker_paths.append(path)

    bot = MagicMock()
    bot.status.return_value = {"running": True}
    bot.stop = AsyncMock()
    bot.start = AsyncMock()
    policy = GitUpdatePolicy(update_timeout_seconds=0.01)
    monkeypatch.setattr(_bot, "GitUpdatePolicy", lambda: policy)
    monkeypatch.setattr(_bot, "_load_release_payload", fake_release_payload)
    monkeypatch.setattr(
        _bot,
        "_check_git_eligibility",
        AsyncMock(
            return_value=GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=tmp_path,
                reason="eligible",
            )
        ),
    )
    monkeypatch.setattr(asyncio, "to_thread", slow_to_thread)
    monkeypatch.setattr(async_io, "write_text", track_marker_write)
    delete_marker = AsyncMock()
    monkeypatch.setattr(async_io, "delete_file", delete_marker)

    response = await _bot.update_restart_handler(
        cast(
            web.Request,
            cast(
                Any,
                _request(
                    json_body={"target_version": "v3.8.0"},
                    bot=bot,
                ),
            ),
        )
    )
    data = _payload(response)
    marker = tmp_path / "data" / "cache" / "pending_bot_autostart"

    assert cast(web.Response, response).status == 500
    assert data == {
        "success": False,
        "error": "update_failed",
        "detail": "TimeoutError",
    }
    assert marker_paths == [marker]
    delete_marker.assert_awaited_once_with(marker)
    bot.stop.assert_awaited_once()
    bot.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_restart_rejects_stale_confirmed_version(
    monkeypatch: pytest.MonkeyPatch,
    _authenticated: None,
) -> None:
    async def fake_release_payload(
        _policy: object,
    ) -> tuple[dict[str, object], None]:
        return (
            {
                "success": True,
                "current_version": "v3.7.0",
                "latest_version": "v3.9.0",
                "update_available": True,
                "release": {"name": "Undefined v3.9.0"},
            },
            None,
        )

    apply_update = MagicMock()
    monkeypatch.setattr(_bot, "_load_release_payload", fake_release_payload)
    monkeypatch.setattr(_bot, "apply_git_release_update", apply_update)

    response = await _bot.update_restart_handler(
        cast(
            web.Request,
            cast(
                Any,
                _request(json_body={"target_version": "v3.8.0"}),
            ),
        )
    )

    assert cast(web.Response, response).status == 409
    assert _payload(response)["error"] == "release_changed"
    apply_update.assert_not_called()
