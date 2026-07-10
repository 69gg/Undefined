"""Git-based self-update helpers.

This module is intentionally conservative:
- Only updates when origin URL matches the official repo and branch is main.
- Only fast-forward updates are allowed.
- If the worktree is dirty, it will skip updating.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from Undefined.utils.file_lock import FileLock


@dataclass(frozen=True)
class GitUpdatePolicy:
    allowed_origin_base: str = "https://github.com/69gg/Undefined"
    release_repo_id: str = "69gg/Undefined"
    allowed_branch: str = "main"
    remote_name: str = "origin"
    remote_branch: str = "main"
    require_clean_worktree: bool = True
    update_submodules: bool = True
    uv_sync_on_lock_change: bool = True
    fetch_timeout_seconds: float = 45.0
    merge_timeout_seconds: float = 90.0
    submodule_timeout_seconds: float = 180.0
    uv_sync_timeout_seconds: float = 20 * 60.0


@dataclass(frozen=True)
class GitUpdateResult:
    eligible: bool
    updated: bool
    repo_root: Path | None
    reason: str
    origin_url: str | None = None
    branch: str | None = None
    old_rev: str | None = None
    new_rev: str | None = None
    remote_rev: str | None = None
    output: str = ""
    uv_synced: bool = False
    uv_sync_attempted: bool = False
    target_tag: str | None = None


_RELEASE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def release_version_tuple(value: str) -> tuple[int, int, int]:
    """Parse the repository's canonical release version format."""
    match = _RELEASE_VERSION_RE.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError(f"非法 Release 版本号: {value}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def normalize_release_tag(value: str) -> str:
    major, minor, patch = release_version_tuple(value)
    return f"v{major}.{minor}.{patch}"


def is_release_newer(*, current_version: str, release_tag: str) -> bool:
    return release_version_tuple(release_tag) > release_version_tuple(current_version)


def _normalize_origin_url(url: str) -> str:
    # Accept https://github.com/69gg/Undefined(.git) with optional trailing slash.
    normalized = url.strip()
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    if normalized.endswith(".git"):
        normalized = normalized[: -len(".git")]
    return normalized


def _run(
    argv: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["GIT_TERMINAL_PROMPT"] = "0"
    # On Windows, disable Git Credential Manager interactivity if present.
    merged_env.setdefault("GCM_INTERACTIVE", "Never")
    if env:
        merged_env.update(dict(env))

    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=merged_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _git(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, timeout_seconds=timeout_seconds)


def resolve_repo_root(start_dir: Path) -> Path | None:
    try:
        proc = _git(
            ["rev-parse", "--show-toplevel"],
            cwd=start_dir,
            timeout_seconds=5.0,
        )
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    root = proc.stdout.strip()
    if not root:
        return None
    return Path(root)


def _read_origin_url(repo_root: Path, remote_name: str) -> str | None:
    proc = _git(
        ["remote", "get-url", remote_name],
        cwd=repo_root,
        timeout_seconds=5.0,
    )
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    return url or None


def _read_branch(repo_root: Path) -> str | None:
    proc = _git(
        ["symbolic-ref", "--short", "HEAD"],
        cwd=repo_root,
        timeout_seconds=5.0,
    )
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def _is_worktree_clean(repo_root: Path) -> bool:
    proc = _git(
        ["status", "--porcelain"],
        cwd=repo_root,
        timeout_seconds=5.0,
    )
    if proc.returncode != 0:
        return False
    return proc.stdout.strip() == ""


def _rev_parse(repo_root: Path, ref: str) -> str | None:
    proc = _git(
        ["rev-parse", ref],
        cwd=repo_root,
        timeout_seconds=10.0,
    )
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _diff_names(repo_root: Path, old_rev: str, new_rev: str) -> set[str]:
    proc = _git(
        ["diff", "--name-only", old_rev, new_rev],
        cwd=repo_root,
        timeout_seconds=20.0,
    )
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _append_process_output(
    output_lines: list[str], process: subprocess.CompletedProcess[str]
) -> None:
    if process.stdout.strip():
        output_lines.append(process.stdout.strip())
    if process.stderr.strip():
        output_lines.append(process.stderr.strip())


def _is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    process = _git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo_root,
        timeout_seconds=10.0,
    )
    return process.returncode == 0


def _sync_updated_checkout(
    *,
    repo_root: Path,
    policy: GitUpdatePolicy,
    old_rev: str,
    new_rev: str,
    output_lines: list[str],
) -> tuple[bool, bool]:
    changed = _diff_names(repo_root, old_rev, new_rev)

    if policy.update_submodules:
        output_lines.append("[self-update] git submodule update --init --recursive")
        try:
            sync_process = _git(
                ["submodule", "sync", "--recursive"],
                cwd=repo_root,
                timeout_seconds=policy.submodule_timeout_seconds,
            )
            _append_process_output(output_lines, sync_process)
            update_process = _git(
                ["submodule", "update", "--init", "--recursive"],
                cwd=repo_root,
                timeout_seconds=policy.submodule_timeout_seconds,
            )
            _append_process_output(output_lines, update_process)
        except subprocess.TimeoutExpired:
            output_lines.append("[self-update] submodule update timed out")

    uv_sync_attempted = policy.uv_sync_on_lock_change and bool(
        {"uv.lock", "pyproject.toml"}.intersection(changed)
    )
    if not uv_sync_attempted:
        return False, False

    output_lines.append("[self-update] uv sync")
    try:
        uv_process = _run(
            ["uv", "sync"],
            cwd=repo_root,
            timeout_seconds=policy.uv_sync_timeout_seconds,
        )
        _append_process_output(output_lines, uv_process)
        return uv_process.returncode == 0, True
    except FileNotFoundError:
        output_lines.append("[self-update] uv not found")
    except subprocess.TimeoutExpired:
        output_lines.append("[self-update] uv sync timed out")
    return False, True


def apply_git_release_update(
    policy: GitUpdatePolicy,
    *,
    release_tag: str,
    start_dir: Path | None = None,
) -> GitUpdateResult:
    """Fast-forward the official main branch to an exact published tag."""
    start = time.perf_counter()
    try:
        target_tag = normalize_release_tag(release_tag)
    except ValueError:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=None,
            reason="invalid_release_tag",
            target_tag=str(release_tag or "") or None,
        )

    cwd = start_dir or Path.cwd()
    repo_root = resolve_repo_root(cwd)
    if repo_root is None:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=None,
            reason="not_a_git_repo",
            target_tag=target_tag,
        )

    # Use a lock under data/cache (gitignored) to avoid concurrent updates.
    lock_path = repo_root / "data" / "cache" / "self_update.lock"

    output_lines: list[str] = []
    with FileLock(lock_path, shared=False):
        eligibility = check_git_update_eligibility(policy, start_dir=repo_root)
        if not eligibility.eligible:
            return replace(eligibility, target_tag=target_tag)

        origin_url = eligibility.origin_url
        branch = eligibility.branch

        old_rev = _rev_parse(repo_root, "HEAD")
        if not old_rev:
            return GitUpdateResult(
                eligible=False,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                reason="cannot_read_head",
                target_tag=target_tag,
            )

        remote_main_ref = f"{policy.remote_name}/{policy.remote_branch}"
        tag_ref = f"refs/tags/{target_tag}"
        output_lines.append(f"[self-update] git fetch {policy.remote_name}")
        try:
            fetch_main_process = _git(
                ["fetch", "--prune", policy.remote_name],
                cwd=repo_root,
                timeout_seconds=policy.fetch_timeout_seconds,
            )
        except FileNotFoundError:
            return GitUpdateResult(
                eligible=False,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                reason="git_not_found",
                target_tag=target_tag,
            )
        except subprocess.TimeoutExpired:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="fetch_timeout",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )
        _append_process_output(output_lines, fetch_main_process)
        if fetch_main_process.returncode != 0:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="fetch_main_failed",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        output_lines.append(
            f"[self-update] git fetch {policy.remote_name} {target_tag}"
        )
        try:
            fetch_tag_process = _git(
                ["fetch", policy.remote_name, f"{tag_ref}:{tag_ref}"],
                cwd=repo_root,
                timeout_seconds=policy.fetch_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="fetch_timeout",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )
        _append_process_output(output_lines, fetch_tag_process)
        if fetch_tag_process.returncode != 0:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="fetch_tag_failed",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        remote_main_rev = _rev_parse(repo_root, remote_main_ref)
        release_rev = _rev_parse(repo_root, f"{tag_ref}^{{commit}}")
        if not remote_main_rev:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="cannot_read_remote_ref",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )
        if not release_rev:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="cannot_read_release_ref",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )
        if not _is_ancestor(repo_root, release_rev, remote_main_rev):
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                remote_rev=release_rev,
                reason="release_not_on_main",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        if release_rev == old_rev:
            elapsed = time.perf_counter() - start
            output_lines.append(f"[self-update] up-to-date ({elapsed:.2f}s)")
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                new_rev=old_rev,
                remote_rev=release_rev,
                reason="up_to_date",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        if not _is_ancestor(repo_root, old_rev, release_rev):
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                remote_rev=release_rev,
                reason="release_not_fast_forward",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        output_lines.append(f"[self-update] git merge --ff-only {target_tag}")
        merge_proc = _git(
            ["merge", "--ff-only", release_rev],
            cwd=repo_root,
            timeout_seconds=policy.merge_timeout_seconds,
        )
        if merge_proc.stdout.strip():
            output_lines.append(merge_proc.stdout.strip())
        if merge_proc.stderr.strip():
            output_lines.append(merge_proc.stderr.strip())
        if merge_proc.returncode != 0:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                remote_rev=release_rev,
                reason="merge_failed",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        new_rev = _rev_parse(repo_root, "HEAD")
        if not new_rev:
            return GitUpdateResult(
                eligible=True,
                updated=True,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                remote_rev=release_rev,
                reason="updated_but_cannot_read_new_head",
                output="\n".join(output_lines),
                target_tag=target_tag,
            )

        uv_synced, uv_sync_attempted = _sync_updated_checkout(
            repo_root=repo_root,
            policy=policy,
            old_rev=old_rev,
            new_rev=new_rev,
            output_lines=output_lines,
        )

        elapsed = time.perf_counter() - start
        output_lines.append(
            f"[self-update] updated: {old_rev[:8]} -> {new_rev[:8]} ({elapsed:.2f}s)"
        )

        return GitUpdateResult(
            eligible=True,
            updated=True,
            repo_root=repo_root,
            origin_url=origin_url,
            branch=branch,
            old_rev=old_rev,
            new_rev=new_rev,
            remote_rev=release_rev,
            reason="updated",
            output="\n".join(output_lines),
            uv_synced=uv_synced,
            uv_sync_attempted=uv_sync_attempted,
            target_tag=target_tag,
        )


def check_git_update_eligibility(
    policy: GitUpdatePolicy, *, start_dir: Path | None = None
) -> GitUpdateResult:
    """Check whether git auto-update is allowed under the policy.

    This does not fetch/merge; it only validates repository + origin + branch (+ clean worktree).
    """

    cwd = start_dir or Path.cwd()
    repo_root = resolve_repo_root(cwd)
    if repo_root is None:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=None,
            reason="not_a_git_repo",
        )

    try:
        origin_url = _read_origin_url(repo_root, policy.remote_name)
        branch = _read_branch(repo_root)
    except FileNotFoundError:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            reason="git_not_found",
        )
    if origin_url is None:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            reason="missing_origin",
        )
    if branch is None:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            origin_url=origin_url,
            reason="detached_head",
        )

    normalized_origin = _normalize_origin_url(origin_url)
    if normalized_origin != policy.allowed_origin_base:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            origin_url=origin_url,
            branch=branch,
            reason="origin_mismatch",
        )
    if branch != policy.allowed_branch:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            origin_url=origin_url,
            branch=branch,
            reason="branch_mismatch",
        )
    if policy.require_clean_worktree and not _is_worktree_clean(repo_root):
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=repo_root,
            origin_url=origin_url,
            branch=branch,
            reason="dirty_worktree",
        )

    return GitUpdateResult(
        eligible=True,
        updated=False,
        repo_root=repo_root,
        origin_url=origin_url,
        branch=branch,
        reason="eligible",
    )


def restart_process(
    *, module: str, argv: list[str] | None = None, chdir: Path | None = None
) -> None:
    """Restart current process by execing `python -m <module>`.

    Notes:
    - This keeps the same interpreter (venv/uv) by using sys.executable.
    - We intentionally avoid reusing sys.argv[0] which may be a non-file name (e.g. `uv run`).
    """

    if chdir is not None:
        try:
            os.chdir(chdir)
        except OSError:
            pass

    args = [sys.executable, "-m", module]
    if argv:
        args.extend(argv)
    os.execv(sys.executable, args)
