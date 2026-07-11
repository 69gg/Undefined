import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined import __version__
from Undefined.config import get_config
from Undefined.github.client import get_latest_public_release
from Undefined.github.models import GitHubReleaseInfo
from Undefined.utils import io as async_io
from Undefined.utils.self_update import (
    GitUpdatePolicy,
    GitUpdateResult,
    apply_git_release_update,
    check_git_update_eligibility,
    is_release_newer,
    normalize_release_tag,
    restart_process,
)
from ._shared import (
    check_auth,
    get_bot,
    get_pending_bot_autostart_marker,
    get_settings,
    routes,
)

logger = logging.getLogger(__name__)

_RELEASE_CACHE_TTL_SECONDS = 15 * 60.0
_release_cache: GitHubReleaseInfo | None = None
_release_cache_expires_at = 0.0
_release_fetch_task: asyncio.Task[GitHubReleaseInfo] | None = None
_release_restart_task: asyncio.Task[None] | None = None


def _truncate(text: str, *, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


def _release_fetch_done(task: asyncio.Task[GitHubReleaseInfo]) -> None:
    global _release_fetch_task
    if _release_fetch_task is task:
        _release_fetch_task = None
    if task.cancelled():
        return
    # Retrieve failures even if every shielded request was cancelled.
    task.exception()


def _release_restart_done(task: asyncio.Task[None]) -> None:
    global _release_restart_task
    if _release_restart_task is task:
        _release_restart_task = None
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "[WebUI][更新] WebUI 重启任务失败: %s: %r",
            type(error).__name__,
            error,
        )


def _reset_release_cache() -> None:
    """Reset process-local state for isolated app instances and tests."""
    global _release_cache, _release_cache_expires_at
    global _release_fetch_task, _release_restart_task
    fetch_task = _release_fetch_task
    restart_task = _release_restart_task
    _release_cache = None
    _release_cache_expires_at = 0.0
    _release_fetch_task = None
    _release_restart_task = None
    if fetch_task is not None and not fetch_task.done():
        fetch_task.cancel()
    if restart_task is not None and not restart_task.done():
        restart_task.cancel()


async def _fetch_latest_release(
    policy: GitUpdatePolicy,
) -> GitHubReleaseInfo:
    global _release_cache, _release_cache_expires_at

    config = get_config(strict=False)
    release = await get_latest_public_release(
        policy.release_repo_id,
        request_timeout=config.github_request_timeout_seconds,
        request_retries=config.github_request_retries,
        context={
            "runtime_config": config,
            "request_id": "webui-update-check",
        },
    )
    _release_cache = release
    _release_cache_expires_at = time.monotonic() + _RELEASE_CACHE_TTL_SECONDS
    return release


async def _get_latest_release_cached(
    policy: GitUpdatePolicy,
) -> tuple[GitHubReleaseInfo, bool]:
    global _release_fetch_task

    now = time.monotonic()
    if _release_cache is not None and now < _release_cache_expires_at:
        return _release_cache, True

    fetch_task = _release_fetch_task
    shared = fetch_task is not None
    if fetch_task is None:
        fetch_task = asyncio.create_task(
            _fetch_latest_release(policy),
            name="webui-release-check",
        )
        fetch_task.add_done_callback(_release_fetch_done)
        _release_fetch_task = fetch_task

    release = await asyncio.shield(fetch_task)
    return release, shared


def _release_response_payload(
    *,
    policy: GitUpdatePolicy,
    release: GitHubReleaseInfo,
    cached: bool,
) -> dict[str, object]:
    latest_version = normalize_release_tag(release.tag_name)
    current_version = normalize_release_tag(__version__)
    update_available = is_release_newer(
        current_version=current_version,
        release_tag=latest_version,
    )
    return {
        "success": True,
        "checked": True,
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "release": {
            "name": release.name or latest_version,
            "url": f"{policy.allowed_origin_base}/releases/tag/{latest_version}",
            "published_at": release.published_at,
        },
        "cached": cached,
    }


async def _load_release_payload(
    policy: GitUpdatePolicy,
) -> tuple[dict[str, object] | None, Response | None]:
    try:
        release, cached = await _get_latest_release_cached(policy)
        return (
            _release_response_payload(
                policy=policy,
                release=release,
                cached=cached,
            ),
            None,
        )
    except Exception as exc:
        logger.warning(
            "[WebUI][更新检查] GitHub Release 查询失败: %s: %r",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return None, web.json_response(
            {"success": False, "error": "release_check_failed"}, status=502
        )


async def _restore_bot_after_update_failure(
    *,
    bot: Any,
    was_running: bool,
    marker: Path,
) -> None:
    if not was_running:
        return
    try:
        await async_io.delete_file(marker)
    except OSError:
        pass
    try:
        await bot.start()
    except Exception:
        logger.warning("[WebUI][更新] 更新失败后恢复 Bot 进程失败", exc_info=True)


async def _check_git_eligibility(policy: GitUpdatePolicy) -> GitUpdateResult:
    try:
        return await asyncio.to_thread(check_git_update_eligibility, policy)
    except Exception:
        logger.warning("[WebUI][更新检查] Git 仓库状态检查失败", exc_info=True)
        return GitUpdateResult(
            eligible=False,
            updated=False,
            repo_root=None,
            reason="git_check_failed",
        )


async def _run_bot_action(request: web.Request, action: str) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    bot = get_bot(request)
    if action == "start":
        return web.json_response(await bot.start())
    if action == "stop":
        return web.json_response(await bot.stop())
    return web.json_response({"error": "Invalid action"}, status=400)


@routes.get("/api/v1/management/status")
@routes.get("/api/status")
async def status_handler(request: web.Request) -> Response:
    bot = get_bot(request)
    status = bot.status()
    if not check_auth(request):
        return web.json_response(
            {"running": bool(status.get("running")), "public": True}
        )
    return web.json_response(status)


@routes.post("/api/v1/management/bot/{action}")
@routes.post("/api/bot/{action}")
async def bot_action_handler(request: web.Request) -> Response:
    return await _run_bot_action(request, request.match_info["action"])


@routes.post("/api/v1/management/bot/start")
async def bot_start_handler(request: web.Request) -> Response:
    return await _run_bot_action(request, "start")


@routes.post("/api/v1/management/bot/stop")
async def bot_stop_handler(request: web.Request) -> Response:
    return await _run_bot_action(request, "stop")


@routes.get("/api/v1/management/update-check")
@routes.get("/api/update-check")
async def update_check_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    manual = str(request.query.get("manual") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    enabled = bool(getattr(get_settings(request), "check_updates", True))
    if not enabled and not manual:
        return web.json_response(
            {
                "success": True,
                "enabled": False,
                "checked": False,
                "update_available": False,
            }
        )

    policy = GitUpdatePolicy()
    payload, error_response = await _load_release_payload(policy)
    if error_response is not None:
        return error_response
    if payload is None:
        return web.json_response(
            {"success": False, "error": "release_check_failed"}, status=502
        )

    payload["enabled"] = enabled
    if bool(payload["update_available"]):
        eligibility = await _check_git_eligibility(policy)
        payload["eligible"] = eligibility.eligible
        payload["reason"] = eligibility.reason
        payload["origin_url"] = eligibility.origin_url
        payload["branch"] = eligibility.branch
    else:
        payload["eligible"] = None
        payload["reason"] = "up_to_date"
    return web.json_response(payload)


@routes.post("/api/v1/management/update-restart")
@routes.post("/api/update-restart")
async def update_restart_handler(request: web.Request) -> Response:
    global _release_restart_task

    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    requested_version = ""
    if bool(getattr(request, "can_read_body", False)):
        try:
            raw_payload = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "invalid_json"}, status=400
            )
        if not isinstance(raw_payload, dict):
            return web.json_response(
                {"success": False, "error": "invalid_json"}, status=400
            )
        requested_version = str(raw_payload.get("target_version") or "").strip()

    policy = GitUpdatePolicy()
    release_payload, error_response = await _load_release_payload(policy)
    if error_response is not None:
        return error_response
    if release_payload is None:
        return web.json_response(
            {"success": False, "error": "release_check_failed"}, status=502
        )
    latest_version = str(release_payload["latest_version"])
    if not bool(release_payload["update_available"]):
        return web.json_response(
            {
                **release_payload,
                "eligible": True,
                "updated": False,
                "reason": "up_to_date",
                "will_restart": False,
            }
        )
    if requested_version:
        try:
            normalized_requested_version = normalize_release_tag(requested_version)
        except ValueError:
            return web.json_response(
                {"success": False, "error": "invalid_release_tag"}, status=400
            )
        if normalized_requested_version != latest_version:
            return web.json_response(
                {
                    "success": False,
                    "error": "release_changed",
                    "latest_version": latest_version,
                    "release": release_payload["release"],
                },
                status=409,
            )

    eligibility = await _check_git_eligibility(policy)
    if not eligibility.eligible:
        return web.json_response(
            {
                "success": True,
                "eligible": False,
                "updated": False,
                "reason": eligibility.reason,
                "origin_url": eligibility.origin_url,
                "branch": eligibility.branch,
                "will_restart": False,
                "output": _truncate(eligibility.output or ""),
                "target_version": latest_version,
            }
        )
    repo_root = eligibility.repo_root
    if repo_root is None:
        logger.warning("[WebUI][更新] Git 仓库状态可更新但缺少仓库根目录")
        return web.json_response(
            {"success": False, "error": "update_failed"}, status=500
        )

    bot = get_bot(request)
    was_running = bool(bot.status().get("running"))
    marker = get_pending_bot_autostart_marker(repo_root)
    if was_running:
        try:
            await asyncio.wait_for(bot.stop(), timeout=8)
        except asyncio.TimeoutError:
            return web.json_response(
                {"success": False, "error": "bot_stop_timeout"}, status=500
            )
        except Exception:
            logger.warning("[WebUI][更新] 停止 Bot 进程失败", exc_info=True)
            return web.json_response(
                {"success": False, "error": "bot_stop_failed"}, status=500
            )
        try:
            await async_io.write_text(marker, "1")
        except OSError:
            logger.warning("[WebUI][更新] 无法写入 Bot 自动恢复标记", exc_info=True)
            await _restore_bot_after_update_failure(
                bot=bot,
                was_running=was_running,
                marker=marker,
            )
            return web.json_response(
                {"success": False, "error": "restore_marker_failed"}, status=500
            )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                apply_git_release_update,
                policy,
                release_tag=latest_version,
                start_dir=repo_root,
            ),
            timeout=policy.update_timeout_seconds,
        )
    except Exception as exc:
        logger.exception("[WebUI][更新] Release 更新执行异常")
        await _restore_bot_after_update_failure(
            bot=bot,
            was_running=was_running,
            marker=marker,
        )
        return web.json_response(
            {
                "success": False,
                "error": "update_failed",
                "detail": type(exc).__name__,
            },
            status=500,
        )
    payload: dict[str, object] = {
        "success": True,
        "eligible": result.eligible,
        "updated": result.updated,
        "reason": result.reason,
        "origin_url": result.origin_url,
        "branch": result.branch,
        "old_rev": result.old_rev,
        "new_rev": result.new_rev,
        "remote_rev": result.remote_rev,
        "uv_synced": result.uv_synced,
        "uv_sync_attempted": result.uv_sync_attempted,
        "target_version": latest_version,
        "output": _truncate(result.output or ""),
    }

    can_restart = not (
        result.updated and result.uv_sync_attempted and not result.uv_synced
    )
    will_restart = bool(
        result.eligible and result.reason in {"updated", "up_to_date"} and can_restart
    )
    payload["will_restart"] = will_restart

    if not will_restart:
        await _restore_bot_after_update_failure(
            bot=bot,
            was_running=was_running,
            marker=marker,
        )
        return web.json_response(payload)

    async def _restart_soon() -> None:
        await asyncio.sleep(0.25)
        restart_process(module="Undefined.webui", chdir=result.repo_root or repo_root)

    if _release_restart_task is None or _release_restart_task.done():
        restart_task = asyncio.create_task(
            _restart_soon(), name="webui-release-restart"
        )
        _release_restart_task = restart_task
        restart_task.add_done_callback(_release_restart_done)
    return web.json_response(payload)
