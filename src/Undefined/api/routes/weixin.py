"""微信 iLink 管理路由。"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response
import qrcode

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error
from Undefined.weixin.service import (
    WeixinConfirmationRequired,
    WeixinConflictError,
    WeixinNotFoundError,
    WeixinServiceError,
    WeixinUpstreamError,
)


def _service(ctx: RuntimeAPIContext) -> Any | None:
    return getattr(ctx, "weixin_service", None)


def _actor(ctx: RuntimeAPIContext) -> str:
    config = ctx.config_getter()
    return f"management:{int(getattr(config, 'superadmin_qq', 0) or 0)}"


async def _json_body(
    request: web.Request,
) -> tuple[dict[str, Any] | None, Response | None]:
    try:
        value = await request.json()
    except Exception:
        return None, _json_error("Invalid JSON", status=400)
    if not isinstance(value, dict):
        return None, _json_error("JSON body must be an object", status=400)
    return value, None


def _parse_qq_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _service_error(exc: Exception) -> Response:
    if isinstance(exc, WeixinConfirmationRequired):
        return web.json_response(
            {
                "error": exc.warning,
                "requires_confirmation": True,
                "confirmation_token": exc.token,
                "expires_at": exc.expires_at,
            },
            status=409,
        )
    if isinstance(exc, WeixinNotFoundError):
        return _json_error(str(exc), status=404)
    if isinstance(exc, WeixinConflictError):
        return _json_error(str(exc), status=409)
    if isinstance(exc, WeixinUpstreamError):
        return _json_error(str(exc), status=502)
    return _json_error(str(exc), status=400)


async def status_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    del request
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    return web.json_response(await service.status())


async def login_start_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    body, error = await _json_body(request)
    if error is not None or body is None:
        return error or _json_error("Invalid JSON")
    alias = str(body.get("alias", "") or "").strip()
    qq_id = _parse_qq_id(body.get("qq_id"))
    if not alias:
        return _json_error("alias is required")
    if qq_id is None:
        return _json_error("qq_id must be a positive integer")
    try:
        result = await service.start_login(
            alias=alias,
            qq_id=qq_id,
            confirmation_token=str(body.get("confirmation_token", "") or "") or None,
            actor=_actor(ctx),
        )
    except WeixinServiceError as exc:
        return _service_error(exc)
    payload = result.to_dict()
    payload.pop("qrcode_payload", None)
    payload["qr_image_url"] = f"/api/v1/weixin/login/{result.session_id}/qr.png"
    return web.json_response(payload, status=201)


async def login_poll_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    session_id = str(request.match_info.get("session_id", "") or "").strip()
    try:
        result = await service.poll_login(session_id, actor=_actor(ctx))
    except WeixinServiceError as exc:
        return _service_error(exc)
    return web.json_response(result.to_dict())


async def login_refresh_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    session_id = str(request.match_info.get("session_id", "") or "").strip()
    try:
        result = await service.refresh_login(session_id)
    except WeixinServiceError as exc:
        return _service_error(exc)
    payload = result.to_dict()
    payload.pop("qrcode_payload", None)
    payload["qr_image_url"] = f"/api/v1/weixin/login/{result.session_id}/qr.png"
    return web.json_response(payload)


async def login_verify_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    body, error = await _json_body(request)
    if error is not None or body is None:
        return error or _json_error("Invalid JSON")
    code = str(body.get("code", "") or "").strip()
    if not code:
        return _json_error("code is required")
    session_id = str(request.match_info.get("session_id", "") or "").strip()
    try:
        await service.submit_verify_code(session_id, code)
    except WeixinServiceError as exc:
        return _service_error(exc)
    except Exception as exc:
        return _json_error(str(exc), status=400)
    return web.json_response({"session_id": session_id, "submitted": True})


async def login_cancel_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    session_id = str(request.match_info.get("session_id", "") or "").strip()
    deleted = await service.cancel_login(session_id)
    if not deleted:
        return _json_error("Login session not found", status=404)
    return web.json_response({"session_id": session_id, "cancelled": True})


async def login_qr_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> web.StreamResponse:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    session_id = str(request.match_info.get("session_id", "") or "").strip()
    try:
        payload = service.get_login_qrcode_payload(session_id)
    except WeixinServiceError as exc:
        return _service_error(exc)
    code = qrcode.QRCode(border=2, box_size=8)
    code.add_data(payload)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return web.Response(
        body=buffer.getvalue(),
        content_type="image/png",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def account_update_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    body, error = await _json_body(request)
    if error is not None or body is None:
        return error or _json_error("Invalid JSON")
    alias = str(request.match_info.get("alias", "") or "").strip()
    try:
        if "qq_id" in body:
            qq_id = _parse_qq_id(body.get("qq_id"))
            if qq_id is None:
                return _json_error("qq_id must be a positive integer")
            account = await service.rebind_account(
                alias,
                qq_id,
                confirmation_token=(
                    str(body.get("confirmation_token", "") or "") or None
                ),
                actor=_actor(ctx),
            )
        elif "enabled" in body and isinstance(body.get("enabled"), bool):
            account = await service.set_account_enabled(
                alias,
                bool(body["enabled"]),
                actor=_actor(ctx),
            )
        else:
            return _json_error("body must contain qq_id or boolean enabled")
    except WeixinServiceError as exc:
        return _service_error(exc)
    return web.json_response({"account": account})


async def account_delete_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    alias = str(request.match_info.get("alias", "") or "").strip()
    try:
        deleted = await service.remove_account(alias, actor=_actor(ctx))
    except WeixinServiceError as exc:
        return _service_error(exc)
    if not deleted:
        return _json_error("Account not found", status=404)
    return web.json_response({"alias": alias, "deleted": True})


async def pending_list_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    del request
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    items = [item.to_dict() for item in await service.store.list_pending_peers()]
    return web.json_response({"total": len(items), "items": items})


async def pending_delete_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    record_id = str(request.match_info.get("record_id", "") or "").strip()
    deleted = await service.store.dismiss_pending_peer(record_id)
    if not deleted:
        return _json_error("Pending peer not found", status=404)
    return web.json_response({"id": record_id, "deleted": True})


async def audit_list_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    service = _service(ctx)
    if service is None:
        return _json_error("WeChat service not ready", status=503)
    try:
        limit = int(request.query.get("limit", "100"))
    except ValueError:
        return _json_error("limit must be an integer")
    items = [item.to_dict() for item in await service.store.list_audit(limit=limit)]
    return web.json_response({"total": len(items), "items": items})
