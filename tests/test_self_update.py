from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

import Undefined.utils.self_update as update_module
from Undefined.utils.self_update import GitUpdatePolicy, GitUpdateResult


@pytest.mark.parametrize(
    ("current", "release", "expected"),
    [
        ("3.7.0", "v3.7.1", True),
        ("3.7.0", "v3.7.0", False),
        ("3.8.0", "v3.7.9", False),
        ("3.9.9", "v4.0.0", True),
    ],
)
def test_is_release_newer(
    current: str,
    release: str,
    expected: bool,
) -> None:
    assert (
        update_module.is_release_newer(
            current_version=current,
            release_tag=release,
        )
        is expected
    )


@pytest.mark.parametrize("value", ["", "latest", "v3.7", "v3.7.0-rc1"])
def test_release_version_tuple_rejects_noncanonical_versions(value: str) -> None:
    with pytest.raises(ValueError, match="非法 Release"):
        update_module.release_version_tuple(value)


def _eligible(repo_root: Path) -> GitUpdateResult:
    return GitUpdateResult(
        eligible=True,
        updated=False,
        repo_root=repo_root,
        reason="eligible",
        origin_url="https://github.com/69gg/Undefined.git",
        branch="main",
    )


def test_apply_git_release_update_fast_forwards_exact_release_tag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_rev = "a" * 40
    release_rev = "b" * 40
    commands: list[list[str]] = []
    head_reads = 0

    def fake_rev_parse(_repo_root: Path, ref: str) -> str | None:
        nonlocal head_reads
        if ref == "HEAD":
            head_reads += 1
            return old_rev if head_reads == 1 else release_rev
        if ref == "origin/main":
            return release_rev
        if ref == "refs/tags/v3.8.0^{commit}":
            return release_rev
        return None

    def fake_git(
        args: list[str],
        *,
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_seconds
        commands.append(list(args))
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(update_module, "resolve_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(
        update_module,
        "check_git_update_eligibility",
        lambda _policy, *, start_dir=None: _eligible(start_dir or tmp_path),
    )
    monkeypatch.setattr(update_module, "_rev_parse", fake_rev_parse)
    monkeypatch.setattr(update_module, "_git", fake_git)
    monkeypatch.setattr(update_module, "_diff_names", lambda *_args: set())

    result = update_module.apply_git_release_update(
        GitUpdatePolicy(update_submodules=False, uv_sync_on_lock_change=False),
        release_tag="v3.8.0",
        start_dir=tmp_path,
    )

    assert result.updated is True
    assert result.reason == "updated"
    assert result.new_rev == release_rev
    assert result.target_tag == "v3.8.0"
    assert ["fetch", "--prune", "origin"] in commands
    assert [
        "fetch",
        "origin",
        "refs/tags/v3.8.0:refs/tags/v3.8.0",
    ] in commands
    assert ["merge", "--ff-only", release_rev] in commands


def test_apply_git_release_update_rejects_non_fast_forward(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_rev = "a" * 40
    release_rev = "b" * 40
    ancestry_checks = iter([True, False])

    monkeypatch.setattr(update_module, "resolve_repo_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(
        update_module,
        "check_git_update_eligibility",
        lambda _policy, *, start_dir=None: _eligible(start_dir or tmp_path),
    )
    monkeypatch.setattr(
        update_module,
        "_rev_parse",
        lambda _root, ref: {
            "HEAD": old_rev,
            "origin/main": release_rev,
            "refs/tags/v3.8.0^{commit}": release_rev,
        }.get(ref),
    )
    monkeypatch.setattr(
        update_module,
        "_git",
        lambda args, **_kwargs: subprocess.CompletedProcess(["git", *args], 0, "", ""),
    )
    monkeypatch.setattr(
        update_module,
        "_is_ancestor",
        lambda *_args: next(ancestry_checks),
    )

    result = update_module.apply_git_release_update(
        GitUpdatePolicy(update_submodules=False, uv_sync_on_lock_change=False),
        release_tag="v3.8.0",
        start_dir=tmp_path,
    )

    assert result.updated is False
    assert result.eligible is True
    assert result.reason == "release_not_fast_forward"


def test_apply_git_release_update_rejects_invalid_tag_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls = 0

    def fake_resolve(_cwd: Path) -> Path | None:
        nonlocal resolve_calls
        resolve_calls += 1
        return None

    monkeypatch.setattr(update_module, "resolve_repo_root", fake_resolve)

    result = update_module.apply_git_release_update(
        GitUpdatePolicy(),
        release_tag="main; rm -rf /",
    )

    assert result.reason == "invalid_release_tag"
    assert result.eligible is False
    assert resolve_calls == 0


def test_sync_updated_checkout_marks_missing_uv_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        update_module,
        "_diff_names",
        lambda *_args: {"uv.lock"},
    )

    def missing_uv(*_args: Any, **_kwargs: Any) -> Any:
        raise FileNotFoundError

    monkeypatch.setattr(update_module, "_run", missing_uv)
    output: list[str] = []

    synced, attempted = update_module._sync_updated_checkout(
        repo_root=tmp_path,
        policy=GitUpdatePolicy(update_submodules=False),
        old_rev="a",
        new_rev="b",
        output_lines=output,
    )

    assert attempted is True
    assert synced is False
    assert "[self-update] uv not found" in output
