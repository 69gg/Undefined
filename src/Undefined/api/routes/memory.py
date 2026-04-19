"""Memory CRUD routes."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error, _optional_query_param, _parse_query_time


async def memory_list_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    query = str(request.query.get("q", "") or "").strip().lower()
    top_k_raw = _optional_query_param(request, "top_k")
    time_from_raw = _optional_query_param(request, "time_from")
    time_to_raw = _optional_query_param(request, "time_to")
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    if memory_storage is None:
        return _json_error("Memory storage not ready", status=503)

    limit: int | None = None
    if top_k_raw is not None:
        try:
            limit = int(top_k_raw)
        except ValueError:
            return _json_error("top_k must be an integer", status=400)
        if limit <= 0:
            return _json_error("top_k must be > 0", status=400)

    time_from_dt = _parse_query_time(time_from_raw)
    if time_from_raw is not None and time_from_dt is None:
        return _json_error("time_from must be ISO datetime", status=400)
    time_to_dt = _parse_query_time(time_to_raw)
    if time_to_raw is not None and time_to_dt is None:
        return _json_error("time_to must be ISO datetime", status=400)
    if time_from_dt and time_to_dt and time_from_dt > time_to_dt:
        time_from_dt, time_to_dt = time_to_dt, time_from_dt

    records = memory_storage.get_all()
    items: list[dict[str, Any]] = []
    for item in records:
        created_at = str(item.created_at or "").strip()
        created_dt = _parse_query_time(created_at)
        if time_from_dt and created_dt and created_dt < time_from_dt:
            continue
        if time_to_dt and created_dt and created_dt > time_to_dt:
            continue
        if (time_from_dt or time_to_dt) and created_dt is None:
            continue
        items.append(
            {
                "uuid": item.uuid,
                "fact": item.fact,
                "created_at": created_at,
            }
        )
    if query:
        items = [
            item
            for item in items
            if query in str(item.get("fact", "")).lower()
            or query in str(item.get("uuid", "")).lower()
        ]

    def _created_sort_key(item: dict[str, Any]) -> float:
        created_dt = _parse_query_time(str(item.get("created_at") or ""))
        if created_dt is None:
            return float("-inf")
        with suppress(OSError, OverflowError, ValueError):
            return float(created_dt.timestamp())
        return float("-inf")

    items.sort(key=_created_sort_key)
    if limit is not None:
        items = items[:limit]

    return web.json_response(
        {
            "total": len(items),
            "items": items,
            "query": {
                "q": query or "",
                "top_k": limit,
                "time_from": time_from_raw,
                "time_to": time_to_raw,
            },
        }
    )


async def memory_create_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    if memory_storage is None:
        return _json_error("Memory storage not ready", status=503)
    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)
    fact = str(body.get("fact", "") or "").strip()
    if not fact:
        return _json_error("fact must not be empty", status=400)
    new_uuid = await memory_storage.add(fact)
    if new_uuid is None:
        return _json_error("Failed to create memory", status=500)
    existing = [m for m in memory_storage.get_all() if m.uuid == new_uuid]
    item = existing[0] if existing else None
    return web.json_response(
        {
            "uuid": new_uuid,
            "fact": item.fact if item else fact,
            "created_at": item.created_at if item else "",
        },
        status=201,
    )


async def memory_update_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    if memory_storage is None:
        return _json_error("Memory storage not ready", status=503)
    target_uuid = str(request.match_info.get("uuid", "")).strip()
    if not target_uuid:
        return _json_error("uuid is required", status=400)
    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)
    fact = str(body.get("fact", "") or "").strip()
    if not fact:
        return _json_error("fact must not be empty", status=400)
    ok = await memory_storage.update(target_uuid, fact)
    if not ok:
        return _json_error(f"Memory {target_uuid} not found", status=404)
    return web.json_response({"uuid": target_uuid, "fact": fact, "updated": True})


async def memory_delete_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    if memory_storage is None:
        return _json_error("Memory storage not ready", status=503)
    target_uuid = str(request.match_info.get("uuid", "")).strip()
    if not target_uuid:
        return _json_error("uuid is required", status=400)
    ok = await memory_storage.delete(target_uuid)
    if not ok:
        return _json_error(f"Memory {target_uuid} not found", status=404)
    return web.json_response({"uuid": target_uuid, "deleted": True})
