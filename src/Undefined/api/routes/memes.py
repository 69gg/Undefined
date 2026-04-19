"""Meme management route handlers."""

from __future__ import annotations

from typing import Any, cast

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error, _optional_query_param, _to_bool


async def meme_list_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)

    def _parse_optional_bool(name: str) -> bool | None:
        raw = request.query.get(name)
        if raw is None or str(raw).strip() == "":
            return None
        return _to_bool(raw)

    page_raw = _optional_query_param(request, "page")
    page_size_raw = _optional_query_param(request, "page_size")
    top_k_raw = _optional_query_param(request, "top_k")
    query = str(request.query.get("q", "") or "").strip()
    query_mode = str(request.query.get("query_mode", "") or "").strip().lower()
    keyword_query = str(request.query.get("keyword_query", "") or "").strip()
    semantic_query = str(request.query.get("semantic_query", "") or "").strip()
    try:
        page = int(page_raw) if page_raw is not None else 1
        page_size = int(page_size_raw) if page_size_raw is not None else 50
        top_k = int(top_k_raw) if top_k_raw is not None else page_size
    except ValueError:
        return _json_error("page/page_size/top_k must be integers", status=400)
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    top_k = max(1, top_k)
    sort = str(request.query.get("sort", "updated_at") or "updated_at").strip()

    enabled_filter = _parse_optional_bool("enabled")
    animated_filter = _parse_optional_bool("animated")
    pinned_filter = _parse_optional_bool("pinned")
    if not (query or keyword_query or semantic_query) and sort == "relevance":
        sort = "updated_at"

    if query or keyword_query or semantic_query:
        has_post_filter = any(
            f is not None for f in (enabled_filter, animated_filter, pinned_filter)
        )
        requested_window = max(page * page_size, top_k)
        if has_post_filter or page > 1 or sort != "relevance":
            fetch_k = min(500, max(requested_window * 4, top_k))
        else:
            fetch_k = min(500, requested_window)
        search_payload = await meme_service.search_memes(
            query,
            query_mode=query_mode or meme_service.default_query_mode,
            keyword_query=keyword_query or None,
            semantic_query=semantic_query or None,
            top_k=fetch_k,
            include_disabled=enabled_filter is not True,
            sort=sort,
        )
        filtered_items: list[dict[str, Any]] = []
        for item in list(search_payload.get("items") or []):
            if (
                enabled_filter is not None
                and bool(item.get("enabled")) != enabled_filter
            ):
                continue
            if (
                animated_filter is not None
                and bool(item.get("is_animated")) != animated_filter
            ):
                continue
            if pinned_filter is not None and bool(item.get("pinned")) != pinned_filter:
                continue
            filtered_items.append(item)
        offset = (page - 1) * page_size
        paged_items = filtered_items[offset : offset + page_size]
        window_total = len(filtered_items)
        fetched_window_count = len(list(search_payload.get("items") or []))
        window_exhausted = fetched_window_count < fetch_k
        has_more = bool(paged_items) and (
            offset + page_size < window_total
            or (not window_exhausted and window_total >= offset + page_size)
        )
        return web.json_response(
            {
                "ok": True,
                "total": None,
                "window_total": window_total,
                "total_exact": False,
                "page": page,
                "page_size": page_size,
                "has_more": has_more,
                "query_mode": search_payload.get("query_mode"),
                "keyword_query": search_payload.get("keyword_query"),
                "semantic_query": search_payload.get("semantic_query"),
                "sort": search_payload.get("sort", sort),
                "items": paged_items,
            }
        )

    payload = await meme_service.list_memes(
        query=query,
        enabled=enabled_filter,
        animated=animated_filter,
        pinned=pinned_filter,
        sort=sort,
        page=page,
        page_size=page_size,
        summary=True,
    )
    return web.json_response(payload)


async def meme_stats_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    _ = request
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    return web.json_response(await meme_service.stats())


async def meme_detail_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    detail = await meme_service.get_meme(uid)
    if detail is None:
        return _json_error("Meme not found", status=404)
    return web.json_response(detail)


async def meme_blob_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    path = await meme_service.blob_path_for_uid(uid, preview=False)
    if path is None:
        return _json_error("Meme blob not found", status=404)
    return cast(Response, web.FileResponse(path=path))


async def meme_preview_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    path = await meme_service.blob_path_for_uid(uid, preview=True)
    if path is None:
        return _json_error("Meme preview not found", status=404)
    return cast(Response, web.FileResponse(path=path))


async def meme_update_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    try:
        payload = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", status=400)
    if not isinstance(payload, dict):
        return _json_error("JSON body must be an object", status=400)
    updated = await meme_service.update_meme(
        uid,
        manual_description=payload.get("manual_description"),
        tags=payload.get("tags"),
        aliases=payload.get("aliases"),
        enabled=payload.get("enabled") if "enabled" in payload else None,
        pinned=payload.get("pinned") if "pinned" in payload else None,
    )
    if updated is None:
        return _json_error("Meme not found", status=404)
    return web.json_response({"ok": True, "record": updated})


async def meme_delete_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    deleted = await meme_service.delete_meme(uid)
    if not deleted:
        return _json_error("Meme not found", status=404)
    return web.json_response({"ok": True, "uid": uid})


async def meme_reanalyze_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    job_id = await meme_service.enqueue_reanalyze(uid)
    if not job_id:
        return _json_error("Meme queue unavailable", status=503)
    return web.json_response({"ok": True, "uid": uid, "job_id": job_id})


async def meme_reindex_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    meme_service = ctx.meme_service
    if meme_service is None or not meme_service.enabled:
        return _json_error("Meme service disabled", status=400)
    uid = str(request.match_info.get("uid", "")).strip()
    job_id = await meme_service.enqueue_reindex(uid)
    if not job_id:
        return _json_error("Meme queue unavailable", status=503)
    return web.json_response({"ok": True, "uid": uid, "job_id": job_id})
