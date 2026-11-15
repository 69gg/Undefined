"""沿用 Runtime API 的统一鉴权；状态中不包含配对凭证。"""

from aiohttp import web

from Undefined.api._context import RuntimeAPIContext


async def status_handler(ctx: RuntimeAPIContext, request: web.Request) -> web.Response:
    service = ctx.chiliarch_service
    if service is None:
        return web.json_response(
            {"enabled": False, "state": "unavailable", "mailbox_ready": False}
        )
    return web.json_response(service.status())
