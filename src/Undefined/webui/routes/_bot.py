import asyncio
import os
from pathlib import Path

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.utils.self_update import (
    GitUpdatePolicy,
    apply_git_update,
    check_git_update_eligibility,
    restart_process,
)
from ._shared import routes, check_auth, get_bot


def _truncate(text: str, *, max_chars: int = 12000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated)"


@routes.get("/api/status")
async def status_handler(request: web.Request) -> Response:
    bot = get_bot(request)
    status = bot.status()
    if not check_auth(request):
        return web.json_response(
            {"running": bool(status.get("running")), "public": True}
        )
    return web.json_response(status)


@routes.post("/api/bot/{action}")
async def bot_action_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)
    action = request.match_info["action"]
    bot = get_bot(request)
    if action == "start":
        return web.json_response(await bot.start())
    elif action == "stop":
        return web.json_response(await bot.stop())
    return web.json_response({"error": "Invalid action"}, status=400)


@routes.post("/api/update-restart")
async def update_restart_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return web.json_response({"error": "Unauthorized"}, status=401)

    policy = GitUpdatePolicy()
    eligibility = await asyncio.to_thread(check_git_update_eligibility, policy)
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
            }
        )

    bot = get_bot(request)
    was_running = bool(bot.status().get("running"))
    try:
        await asyncio.wait_for(bot.stop(), timeout=8)
    except asyncio.TimeoutError:
        return web.json_response(
            {"success": False, "error": "Bot stop timeout"}, status=500
        )

    if was_running:
        marker = Path("data/cache/pending_bot_autostart")
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_text("1", encoding="utf-8")
        except OSError:
            pass

    result = await asyncio.to_thread(apply_git_update, policy)
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
        if was_running:
            try:
                Path("data/cache/pending_bot_autostart").unlink(missing_ok=True)
            except OSError:
                pass
            try:
                await bot.start()
            except Exception:
                pass
        return web.json_response(payload)

    async def _restart_soon() -> None:
        await asyncio.sleep(0.25)
        if result.repo_root is not None:
            try:
                os.chdir(result.repo_root)
            except OSError:
                pass
        restart_process(module="Undefined.webui", chdir=None)

    asyncio.create_task(_restart_soon())
    return web.json_response(payload)
