"""Health check route."""

from __future__ import annotations

from datetime import datetime

from aiohttp.web_response import Response
from aiohttp import web

from Undefined import __version__
from Undefined.api._context import RuntimeAPIContext


async def health_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    _ = ctx, request
    return web.json_response(
        {
            "ok": True,
            "service": "undefined-runtime-api",
            "version": __version__,
            "timestamp": datetime.now().isoformat(),
        }
    )
