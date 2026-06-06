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

    async def fake_request_with_retry(
        _method: str,
        url: str,
        **_kwargs: Any,
    ) -> _FakeResponse:
        calls.append(url)
        if url.endswith("/contributors"):
            return _FakeResponse(
                [{"login": "alice"}],
                {
                    "link": '<https://api.github.com/repositories/1/contributors?per_page=1&page=42>; rel="last"'
                },
            )
        return _FakeResponse(_repo_payload())

    monkeypatch.setattr(client_module, "request_with_retry", fake_request_with_retry)

    info = await client_module.get_public_repo_info("69gg/Undefined")

    assert calls == [
        "https://api.github.com/repos/69gg/Undefined",
        "https://api.github.com/repos/69gg/Undefined/contributors",
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
