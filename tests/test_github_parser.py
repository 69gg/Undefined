from __future__ import annotations

import json

from Undefined.github.parser import (
    extract_from_json_message,
    extract_github_repo_ids,
    normalize_github_repo_id,
)


def test_normalize_github_repo_id_from_links_and_bare_id() -> None:
    assert (
        normalize_github_repo_id("https://github.com/69gg/Undefined/issues/1")
        == "69gg/Undefined"
    )
    assert normalize_github_repo_id("git@github.com:owner/repo.git") == "owner/repo"
    assert normalize_github_repo_id("microsoft/vscode") == "microsoft/vscode"


def test_extract_github_repo_ids_deduplicates_links_and_bare_ids() -> None:
    text = (
        "看 https://github.com/69gg/Undefined 和 69gg/Undefined，"
        "还有 github.com/python/cpython/tree/main"
    )

    assert extract_github_repo_ids(text) == ["69gg/Undefined", "python/cpython"]


def test_extract_from_json_message_collects_nested_links() -> None:
    payload = {"meta": {"desc": "repo: https://github.com/psf/requests"}}
    segments = [{"type": "json", "data": {"data": json.dumps(payload)}}]

    assert extract_from_json_message(segments) == ["psf/requests"]


def test_invalid_github_repo_ids_are_ignored() -> None:
    assert normalize_github_repo_id("https://gist.github.com/user/123") is None
    assert normalize_github_repo_id("bad_owner/repo") is None
