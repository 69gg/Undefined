"""Naga 解绑路由。"""

from __future__ import annotations

import logging
import uuid as _uuid

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _json_error,
)
from Undefined.api.routes.naga.auth import verify_naga_api_key

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# POST /api/v1/naga/unbind
# ------------------------------------------------------------------


async def naga_unbind_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    """POST /api/v1/naga/unbind — 远端主动解绑。"""
    trace_id = _uuid.uuid4().hex[:8]
    auth_err = verify_naga_api_key(ctx, request)
    if auth_err is not None:
        logger.warning(
            "[NagaUnbind] 鉴权失败: trace=%s remote=%s err=%s",
            trace_id,
            getattr(request, "remote", None),
            auth_err,
        )
        return _json_error("Unauthorized", status=401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)

    bind_uuid = str(body.get("bind_uuid", "") or "").strip()
    naga_id = str(body.get("naga_id", "") or "").strip()
    delivery_signature = str(body.get("delivery_signature", "") or "").strip()
    if not bind_uuid or not naga_id or not delivery_signature:
        return _json_error(
            "bind_uuid, naga_id and delivery_signature are required",
            status=400,
        )
    logger.info(
        "[NagaUnbind] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s signature=%s",
        trace_id,
        getattr(request, "remote", None),
        naga_id,
        bind_uuid,
        delivery_signature[:12] + "...",
    )

    naga_store = ctx.naga_store
    if naga_store is None:
        return _json_error("Naga integration not available", status=503)

    # 解绑时等待在途投递完成，避免消息发到已吊销绑定。
    binding, changed, err = await naga_store.revoke_binding(
        naga_id,
        expected_bind_uuid=bind_uuid,
        delivery_signature=delivery_signature,
    )
    if binding is None:
        logger.warning(
            "[NagaUnbind] 吊销失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
            trace_id,
            naga_id,
            bind_uuid,
            err.message if err is not None else "binding not found",
        )
        return _json_error(
            err.message if err is not None else "binding not found",
            status=err.http_status if err is not None else 404,
        )
    logger.info(
        "[NagaUnbind] 吊销完成: trace=%s naga_id=%s bind_uuid=%s changed=%s qq=%s group=%s",
        trace_id,
        naga_id,
        bind_uuid,
        changed,
        binding.qq_id,
        binding.group_id,
    )
    return web.json_response(
        {
            "ok": True,
            "idempotent": not changed,
            "naga_id": naga_id,
            "bind_uuid": bind_uuid,
        }
    )
