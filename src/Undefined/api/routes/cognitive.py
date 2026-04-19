"""Cognitive event & profile routes."""

from __future__ import annotations

from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error, _optional_query_param


async def cognitive_events_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    cognitive_service = ctx.cognitive_service
    if not cognitive_service or not cognitive_service.enabled:
        return _json_error("Cognitive service disabled", status=400)

    query = str(request.query.get("q", "") or "").strip()
    if not query:
        return _json_error("q is required", status=400)

    search_kwargs: dict[str, Any] = {"query": query}
    for key in (
        "target_user_id",
        "target_group_id",
        "sender_id",
        "request_type",
        "top_k",
        "time_from",
        "time_to",
    ):
        value = _optional_query_param(request, key)
        if value is not None:
            search_kwargs[key] = value

    results = await cognitive_service.search_events(**search_kwargs)
    return web.json_response({"count": len(results), "items": results})


async def cognitive_profiles_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    cognitive_service = ctx.cognitive_service
    if not cognitive_service or not cognitive_service.enabled:
        return _json_error("Cognitive service disabled", status=400)

    query = str(request.query.get("q", "") or "").strip()
    if not query:
        return _json_error("q is required", status=400)

    search_kwargs: dict[str, Any] = {"query": query}
    entity_type = _optional_query_param(request, "entity_type")
    if entity_type is not None:
        search_kwargs["entity_type"] = entity_type
    top_k = _optional_query_param(request, "top_k")
    if top_k is not None:
        search_kwargs["top_k"] = top_k

    results = await cognitive_service.search_profiles(**search_kwargs)
    return web.json_response({"count": len(results), "items": results})


async def cognitive_profile_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    cognitive_service = ctx.cognitive_service
    if not cognitive_service or not cognitive_service.enabled:
        return _json_error("Cognitive service disabled", status=400)

    entity_type = str(request.match_info.get("entity_type", "")).strip()
    entity_id = str(request.match_info.get("entity_id", "")).strip()
    if not entity_type or not entity_id:
        return _json_error("entity_type/entity_id are required", status=400)

    profile = await cognitive_service.get_profile(entity_type, entity_id)
    return web.json_response(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "profile": profile or "",
            "found": bool(profile),
        }
    )
