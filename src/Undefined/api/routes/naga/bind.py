"""Naga 绑定回调路由。"""

from __future__ import annotations

import logging
import uuid as _uuid

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _json_error,
    _short_text_preview,
)
from Undefined.api.routes.naga.auth import verify_naga_api_key

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# POST /api/v1/naga/bind/callback
# ------------------------------------------------------------------


async def naga_bind_callback_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    """POST /api/v1/naga/bind/callback — Naga 绑定回调。"""
    trace_id = _uuid.uuid4().hex[:8]
    auth_err = verify_naga_api_key(ctx, request)
    if auth_err is not None:
        logger.warning(
            "[NagaBindCallback] 鉴权失败: trace=%s remote=%s err=%s",
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
    status = str(body.get("status", "") or "").strip().lower()
    delivery_signature = str(body.get("delivery_signature", "") or "").strip()
    reason = str(body.get("reason", "") or "").strip()
    if not bind_uuid or not naga_id:
        return _json_error("bind_uuid and naga_id are required", status=400)
    if status not in {"approved", "rejected"}:
        return _json_error("status must be 'approved' or 'rejected'", status=400)
    logger.info(
        "[NagaBindCallback] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s status=%s reason=%s signature=%s",
        trace_id,
        getattr(request, "remote", None),
        naga_id,
        bind_uuid,
        status,
        _short_text_preview(reason, limit=60),
        delivery_signature[:12] + "..." if delivery_signature else "",
    )

    naga_store = ctx.naga_store
    if naga_store is None:
        return _json_error("Naga integration not available", status=503)

    sender = ctx.sender
    if status == "approved":
        if not delivery_signature:
            return _json_error(
                "delivery_signature is required when approved", status=400
            )
        # 激活绑定：写入 delivery_signature 并移出 pending 队列。
        binding, created, err = await naga_store.activate_binding(
            bind_uuid=bind_uuid,
            naga_id=naga_id,
            delivery_signature=delivery_signature,
        )
        if err:
            logger.warning(
                "[NagaBindCallback] 激活失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
                trace_id,
                naga_id,
                bind_uuid,
                err.message,
            )
            return _json_error(err.message, status=err.http_status)
        logger.info(
            "[NagaBindCallback] 激活完成: trace=%s naga_id=%s bind_uuid=%s created=%s qq=%s",
            trace_id,
            naga_id,
            bind_uuid,
            created,
            binding.qq_id if binding is not None else "",
        )
        if created and binding is not None and sender is not None:
            try:
                await sender.send_private_message(
                    binding.qq_id,
                    f"🎉 你的 Naga 绑定已生效\nnaga_id: {naga_id}",
                )
            except Exception as exc:
                logger.warning("[NagaBindCallback] 通知绑定成功失败: %s", exc)
        return web.json_response(
            {
                "ok": True,
                "status": "approved",
                "idempotent": not created,
                "naga_id": naga_id,
                "bind_uuid": bind_uuid,
            }
        )

    # --- rejected ---
    pending, removed, err = await naga_store.reject_binding(
        bind_uuid=bind_uuid,
        naga_id=naga_id,
        reason=reason,
    )
    if err:
        logger.warning(
            "[NagaBindCallback] 拒绝失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
            trace_id,
            naga_id,
            bind_uuid,
            err.message,
        )
        return _json_error(err.message, status=err.http_status)
    logger.info(
        "[NagaBindCallback] 拒绝完成: trace=%s naga_id=%s bind_uuid=%s removed=%s qq=%s",
        trace_id,
        naga_id,
        bind_uuid,
        removed,
        pending.qq_id if pending is not None else "",
    )
    if removed and pending is not None and sender is not None:
        try:
            detail = f"\n原因: {reason}" if reason else ""
            await sender.send_private_message(
                pending.qq_id,
                f"❌ 你的 Naga 绑定被远端拒绝\nnaga_id: {naga_id}{detail}",
            )
        except Exception as exc:
            logger.warning("[NagaBindCallback] 通知绑定拒绝失败: %s", exc)
    return web.json_response(
        {
            "ok": True,
            "status": "rejected",
            "idempotent": not removed,
            "naga_id": naga_id,
            "bind_uuid": bind_uuid,
        }
    )
