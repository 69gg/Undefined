from __future__ import annotations

from typing import Any

import pytest

import Undefined.github.client as client_module


class _FakeResponse:
    def __init__(self, payload: object, headers: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


def _repo_payload() -> dict[str, Any]:
    return {
        "full_name": "69gg/Undefined",
        "name": "Undefined",
        "owner": {
            "login": "69gg",
            "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
        },
        "description": "QQ bot platform",
        "html_url": "https://github.com/69gg/Undefined",
        "stargazers_count": 1234,
        "forks_count": 56,
        "open_issues_count": 7,
        "watchers_count": 1234,
        "subscribers_count": 89,
        "language": "Python",
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "default_branch": "main",
        "topics": ["bot", "onebot"],
        "created_at": "2024-01-02T03:04:05Z",
        "updated_at": "2026-05-01T03:04:05Z",
        "pushed_at": "2026-05-01T03:04:05Z",
        "archived": False,
        "fork": False,
        "private": False,
    }


@pytest.mark.asyncio
async def test_get_public_repo_info_parses_repo_and_contributor_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    request_kwargs: list[dict[str, Any]] = []

    async def fake_request_with_retry(
        _method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        calls.append(url)
        request_kwargs.append(kwargs)
        if url.endswith("/contributors"):
            return _FakeResponse(
                [{"login": "alice"}],
                {
                    "link": '<https://api.github.com/repositories/1/contributors?per_page=1&page=42>; rel="last"'
                },
            )
        return _FakeResponse(_repo_payload())

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    info = await client_module.get_public_repo_info(
        "69gg/Undefined",
        request_timeout=17.0,
        request_retries=3,
        context={"request_id": "github-test"},
    )

    assert calls == [
        "https://api.github.com/repos/69gg/Undefined",
        "https://api.github.com/repos/69gg/Undefined/contributors",
    ]
    assert [item["timeout"] for item in request_kwargs] == [17.0, 17.0]
    assert [item["retries"] for item in request_kwargs] == [3, 3]
    assert [item["context"] for item in request_kwargs] == [
        {"request_id": "github-test"},
        {"request_id": "github-test"},
    ]
    assert info.repo_id == "69gg/Undefined"
    assert info.owner_login == "69gg"
    assert info.stars == 1234
    assert info.forks == 56
    assert info.open_issues == 7
    assert info.watchers == 89
    assert info.subscribers == 89
    assert info.contributors == 42
    assert info.topics == ("bot", "onebot")


@pytest.mark.asyncio
async def test_get_public_repo_info_rejects_private_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request_with_retry(
        _method: str,
        _url: str,
        **_kwargs: Any,
    ) -> _FakeResponse:
        payload = _repo_payload()
        payload["private"] = True
        return _FakeResponse(payload)

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    with pytest.raises(ValueError, match="仅支持 public"):
        await client_module.get_public_repo_info("69gg/Undefined")


@pytest.mark.asyncio
async def test_get_public_repo_info_uses_default_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_kwargs: list[dict[str, Any]] = []

    async def fake_request_with_retry(
        _method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        request_kwargs.append(kwargs)
        if url.endswith("/contributors"):
            return _FakeResponse([{"login": "alice"}])
        return _FakeResponse(_repo_payload())

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    await client_module.get_public_repo_info("69gg/Undefined")

    assert [item["timeout"] for item in request_kwargs] == [
        client_module.DEFAULT_REQUEST_TIMEOUT_SECONDS,
        client_module.DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ]
    assert [item["retries"] for item in request_kwargs] == [
        client_module.DEFAULT_REQUEST_RETRIES,
        client_module.DEFAULT_REQUEST_RETRIES,
    ]


@pytest.mark.asyncio
async def test_get_latest_public_release_parses_release_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> _FakeResponse:
        captured.update({"method": method, "url": url, **kwargs})
        return _FakeResponse(
            {
                "tag_name": "v3.8.0",
                "name": "Undefined v3.8.0",
                "html_url": "https://github.com/69gg/Undefined/releases/tag/v3.8.0",
                "published_at": "2026-07-10T08:00:00Z",
                "target_commitish": "main",
                "draft": False,
                "prerelease": False,
            }
        )

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    release = await client_module.get_latest_public_release(
        "https://github.com/69gg/Undefined",
        request_timeout=12.0,
        request_retries=1,
        context={"request_id": "release-test"},
    )

    assert release.tag_name == "v3.8.0"
    assert release.name == "Undefined v3.8.0"
    assert release.target_commitish == "main"
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/repos/69gg/Undefined/releases/latest")
    assert captured["timeout"] == 12.0
    assert captured["retries"] == 1
    assert captured["proxy_scope"] == "github"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": "missing tag"}, "tag_name"),
        ({"tag_name": "v3.8.0", "draft": True}, "正式版本"),
        ({"tag_name": "v3.8.0", "prerelease": True}, "正式版本"),
    ],
)
async def test_get_latest_public_release_rejects_invalid_release(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    message: str,
) -> None:
    async def fake_request_with_retry(
        _method: str,
        _url: str,
        **_kwargs: Any,
    ) -> _FakeResponse:
        return _FakeResponse(payload)

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    with pytest.raises(ValueError, match=message):
        await client_module.get_latest_public_release("69gg/Undefined")
