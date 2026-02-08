"""Git-based self-update helpers.

This module is intentionally conservative:
- Only updates when origin URL matches the official repo and branch is main.
- Only fast-forward updates are allowed.
- If the worktree is dirty, it will skip updating.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from Undefined.utils.file_lock import FileLock


@dataclass(frozen=True)
class GitUpdatePolicy:
    allowed_origin_base: str = "https://github.com/69gg/Undefined"
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


def apply_git_update(
    policy: GitUpdatePolicy, *, start_dir: Path | None = None
) -> GitUpdateResult:
    start = time.perf_counter()
    cwd = start_dir or Path.cwd()
    repo_root = resolve_repo_root(cwd)
    if repo_root is None:
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=None,
            reason="not_a_git_repo",
        )

    # Use a lock under data/cache (gitignored) to avoid concurrent updates.
    lock_path = repo_root / "data" / "cache" / "self_update.lock"

    output_lines: list[str] = []
    with FileLock(lock_path, shared=False):
        origin_url = _read_origin_url(repo_root, policy.remote_name)
        branch = _read_branch(repo_root)

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

        old_rev = _rev_parse(repo_root, "HEAD")
        if not old_rev:
            return GitUpdateResult(
                eligible=False,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                reason="cannot_read_head",
            )

        # Fetch and compare.
        fetch_ref = f"{policy.remote_name}/{policy.remote_branch}"
        output_lines.append(
            f"[self-update] git fetch {policy.remote_name} {policy.remote_branch}"
        )
        try:
            fetch_proc = _git(
                ["fetch", "--prune", policy.remote_name, policy.remote_branch],
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
            )
        if fetch_proc.stdout.strip():
            output_lines.append(fetch_proc.stdout.strip())
        if fetch_proc.stderr.strip():
            output_lines.append(fetch_proc.stderr.strip())
        if fetch_proc.returncode != 0:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="fetch_failed",
                output="\n".join(output_lines),
            )

        remote_rev = _rev_parse(repo_root, fetch_ref)
        if not remote_rev:
            return GitUpdateResult(
                eligible=True,
                updated=False,
                repo_root=repo_root,
                origin_url=origin_url,
                branch=branch,
                old_rev=old_rev,
                reason="cannot_read_remote_ref",
                output="\n".join(output_lines),
            )

        if remote_rev == old_rev:
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
                remote_rev=remote_rev,
                reason="up_to_date",
                output="\n".join(output_lines),
            )

        # Fast-forward merge.
        output_lines.append(f"[self-update] git merge --ff-only {fetch_ref}")
        merge_proc = _git(
            ["merge", "--ff-only", fetch_ref],
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
                remote_rev=remote_rev,
                reason="merge_failed",
                output="\n".join(output_lines),
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
                remote_rev=remote_rev,
                reason="updated_but_cannot_read_new_head",
                output="\n".join(output_lines),
            )

        changed = _diff_names(repo_root, old_rev, new_rev)

        # Submodules (repo contains a submodule).
        if policy.update_submodules:
            # Always safe to run after update; it is a no-op if no submodules.
            output_lines.append("[self-update] git submodule update --init --recursive")
            sync_proc = _git(
                ["submodule", "sync", "--recursive"],
                cwd=repo_root,
                timeout_seconds=policy.submodule_timeout_seconds,
            )
            if sync_proc.stdout.strip():
                output_lines.append(sync_proc.stdout.strip())
            if sync_proc.stderr.strip():
                output_lines.append(sync_proc.stderr.strip())
            update_proc = _git(
                ["submodule", "update", "--init", "--recursive"],
                cwd=repo_root,
                timeout_seconds=policy.submodule_timeout_seconds,
            )
            if update_proc.stdout.strip():
                output_lines.append(update_proc.stdout.strip())
            if update_proc.stderr.strip():
                output_lines.append(update_proc.stderr.strip())
            # If submodule update fails, we still consider the main repo updated.

        uv_synced = False
        uv_sync_attempted = False
        if policy.uv_sync_on_lock_change and (
            "uv.lock" in changed or "pyproject.toml" in changed
        ):
            output_lines.append("[self-update] uv sync")
            uv_sync_attempted = True
            try:
                uv_proc = _run(
                    ["uv", "sync"],
                    cwd=repo_root,
                    timeout_seconds=policy.uv_sync_timeout_seconds,
                )
                if uv_proc.stdout.strip():
                    output_lines.append(uv_proc.stdout.strip())
                if uv_proc.stderr.strip():
                    output_lines.append(uv_proc.stderr.strip())
                uv_synced = uv_proc.returncode == 0
            except FileNotFoundError:
                output_lines.append("[self-update] uv not found; skip uv sync")
                uv_sync_attempted = False

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
            remote_rev=remote_rev,
            reason="updated",
            output="\n".join(output_lines),
            uv_synced=uv_synced,
            uv_sync_attempted=uv_sync_attempted,
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

    origin_url = _read_origin_url(repo_root, policy.remote_name)
    branch = _read_branch(repo_root)
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


def format_update_result(result: GitUpdateResult) -> str:
    parts: list[str] = []
    parts.append(
        f"eligible={result.eligible} updated={result.updated} reason={result.reason}"
    )
    if result.origin_url:
        parts.append(f"origin={result.origin_url}")
    if result.branch:
        parts.append(f"branch={result.branch}")
    if result.old_rev and result.new_rev:
        parts.append(f"rev={result.old_rev[:8]}->{result.new_rev[:8]}")
    if result.output.strip():
        parts.append("output:\n" + result.output.strip())
    return " | ".join(parts)


def shell_quote_command(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)
