"""Naga integration route handlers.

Extracted from ``RuntimeAPI`` methods into free functions so they can be
registered declaratively in the route table.
"""

from __future__ import annotations

import logging
import os
import uuid as _uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _json_error,
    _naga_message_digest,
    _parse_response_payload,
    _short_text_preview,
)
from Undefined.api._naga_state import NagaState
from Undefined.render import render_html_to_image, render_markdown_to_html

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Auth helper
# ------------------------------------------------------------------


def verify_naga_api_key(ctx: RuntimeAPIContext, request: web.Request) -> str | None:
    """校验 Naga 共享密钥，返回错误信息或 ``None`` 表示通过。"""
    import secrets as _secrets

    cfg = ctx.config_getter()
    expected = cfg.naga.api_key
    if not expected:
        return "naga api_key not configured"
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "missing or invalid Authorization header"
    provided = auth_header[7:]
    if not _secrets.compare_digest(provided, expected):
        return "invalid api_key"
    return None


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


# ------------------------------------------------------------------
# POST /api/v1/naga/messages/send
# ------------------------------------------------------------------


async def naga_messages_send_handler(
    ctx: RuntimeAPIContext,
    naga_state: NagaState,
    request: web.Request,
) -> Response:
    """POST /api/v1/naga/messages/send — 验签后发送消息。"""
    from Undefined.api.naga_store import mask_token

    trace_id = _uuid.uuid4().hex[:8]
    auth_err = verify_naga_api_key(ctx, request)
    if auth_err is not None:
        logger.warning("[NagaSend] 鉴权失败: trace=%s err=%s", trace_id, auth_err)
        return _json_error("Unauthorized", status=401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)

    bind_uuid = str(body.get("bind_uuid", "") or "").strip()
    naga_id = str(body.get("naga_id", "") or "").strip()
    delivery_signature = str(body.get("delivery_signature", "") or "").strip()
    request_uuid = str(body.get("uuid", "") or "").strip()
    target = body.get("target")
    message = body.get("message")
    if not bind_uuid or not naga_id or not delivery_signature:
        return _json_error(
            "bind_uuid, naga_id and delivery_signature are required",
            status=400,
        )
    if not isinstance(target, dict):
        return _json_error("target object is required", status=400)
    if not isinstance(message, dict):
        return _json_error("message object is required", status=400)

    raw_target_qq = target.get("qq_id")
    raw_target_group = target.get("group_id")
    if raw_target_qq is None or raw_target_group is None:
        return _json_error("target.qq_id and target.group_id are required", status=400)
    try:
        target_qq = int(raw_target_qq)
        target_group = int(raw_target_group)
    except Exception:
        return _json_error(
            "target.qq_id and target.group_id must be integers", status=400
        )
    mode = str(target.get("mode", "") or "").strip().lower()
    if mode not in {"private", "group", "both"}:
        return _json_error(
            "target.mode must be 'private', 'group', or 'both'", status=400
        )

    fmt = str(message.get("format", "text") or "text").strip().lower()
    content = str(message.get("content", "") or "").strip()
    if fmt not in {"text", "markdown", "html"}:
        return _json_error(
            "message.format must be 'text', 'markdown', or 'html'", status=400
        )
    if not content:
        return _json_error("message.content is required", status=400)

    message_key = _naga_message_digest(
        bind_uuid=bind_uuid,
        naga_id=naga_id,
        target_qq=target_qq,
        target_group=target_group,
        mode=mode,
        message_format=fmt,
        content=content,
    )
    logger.info(
        "[NagaSend] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s request_uuid=%s mode=%s fmt=%s qq=%s group=%s key=%s content_len=%s preview=%s signature=%s",
        trace_id,
        getattr(request, "remote", None),
        naga_id,
        bind_uuid,
        request_uuid,
        mode,
        fmt,
        target_qq,
        target_group,
        message_key,
        len(content),
        _short_text_preview(content),
        mask_token(delivery_signature),
    )
    if mode == "both":
        logger.warning(
            "[NagaSend] 上游请求显式要求双路投递: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
            trace_id,
            naga_id,
            bind_uuid,
            request_uuid,
            message_key,
        )
    inflight_count = await naga_state.track_send_start(message_key)
    if inflight_count > 1:
        logger.warning(
            "[NagaSend] 检测到相同 payload 并发请求: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s inflight=%s",
            trace_id,
            naga_id,
            bind_uuid,
            request_uuid,
            message_key,
            inflight_count,
        )
    try:
        if request_uuid:
            dedupe_action, dedupe_value = await naga_state.register_request_uuid(
                request_uuid, message_key
            )
            if dedupe_action == "conflict":
                logger.warning(
                    "[NagaSend] uuid 与历史 payload 冲突: trace=%s naga_id=%s bind_uuid=%s uuid=%s key=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    request_uuid,
                    message_key,
                )
                return _json_error("uuid reused with different payload", status=409)
            if dedupe_action == "cached":
                cached_status, cached_payload = dedupe_value
                logger.warning(
                    "[NagaSend] 命中已完成幂等结果，直接复用: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    request_uuid,
                    message_key,
                )
                return web.json_response(
                    deepcopy(cached_payload),
                    status=int(cached_status),
                )
            if dedupe_action == "await":
                wait_future = dedupe_value
                logger.warning(
                    "[NagaSend] 命中进行中幂等请求，等待首个结果: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    request_uuid,
                    message_key,
                )
                cached_status, cached_payload = await wait_future
                return web.json_response(
                    deepcopy(cached_payload),
                    status=int(cached_status),
                )

        response = await naga_messages_send_impl(
            ctx,
            naga_id=naga_id,
            bind_uuid=bind_uuid,
            delivery_signature=delivery_signature,
            target_qq=target_qq,
            target_group=target_group,
            mode=mode,
            message_format=fmt,
            content=content,
            trace_id=trace_id,
            message_key=message_key,
        )
        if request_uuid:
            await naga_state.finish_request_uuid(
                request_uuid,
                message_key,
                status=response.status,
                payload=_parse_response_payload(response),
            )
        return response
    except Exception as exc:
        if request_uuid:
            await naga_state.fail_request_uuid(request_uuid, message_key, exc)
        raise
    finally:
        remaining = await naga_state.track_send_done(message_key)
        logger.info(
            "[NagaSend] 请求退出: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s inflight_remaining=%s",
            trace_id,
            naga_id,
            bind_uuid,
            request_uuid,
            message_key,
            remaining,
        )


# ------------------------------------------------------------------
# Core send implementation (no NagaState dependency)
# ------------------------------------------------------------------


async def naga_messages_send_impl(
    ctx: RuntimeAPIContext,
    *,
    naga_id: str,
    bind_uuid: str,
    delivery_signature: str,
    target_qq: int,
    target_group: int,
    mode: str,
    message_format: str,
    content: str,
    trace_id: str,
    message_key: str,
) -> Response:
    from Undefined.api.naga_store import mask_token

    naga_store = ctx.naga_store
    if naga_store is None:
        logger.warning(
            "[NagaSend] NagaStore 不可用: trace=%s naga_id=%s bind_uuid=%s",
            trace_id,
            naga_id,
            bind_uuid,
        )
        return _json_error("Naga integration not available", status=503)

    binding, err_msg = await naga_store.acquire_delivery(
        naga_id=naga_id,
        bind_uuid=bind_uuid,
        delivery_signature=delivery_signature,
    )
    if binding is None:
        logger.warning(
            "[NagaSend] 签名校验失败: trace=%s naga_id=%s bind_uuid=%s reason=%s signature=%s",
            trace_id,
            naga_id,
            bind_uuid,
            err_msg.message if err_msg is not None else "unknown_error",
            mask_token(delivery_signature),
        )
        return _json_error(
            err_msg.message if err_msg is not None else "delivery not available",
            status=err_msg.http_status if err_msg is not None else 403,
        )

    logger.info(
        "[NagaSend] 投递凭证已占用: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s group=%s",
        trace_id,
        naga_id,
        bind_uuid,
        message_key,
        binding.qq_id,
        binding.group_id,
    )
    try:
        if target_qq != binding.qq_id or target_group != binding.group_id:
            logger.warning(
                "[NagaSend] 目标不匹配: trace=%s naga_id=%s bind_uuid=%s target_qq=%s target_group=%s bound_qq=%s bound_group=%s",
                trace_id,
                naga_id,
                bind_uuid,
                target_qq,
                target_group,
                binding.qq_id,
                binding.group_id,
            )
            return _json_error("target does not match bound qq/group", status=403)

        cfg = ctx.config_getter()
        if mode == "group" and binding.group_id not in cfg.naga.allowed_groups:
            logger.warning(
                "[NagaSend] 群投递被策略拒绝: trace=%s naga_id=%s bind_uuid=%s group=%s",
                trace_id,
                naga_id,
                bind_uuid,
                binding.group_id,
            )
            return _json_error("bound group is not in naga.allowed_groups", status=403)

        sender = ctx.sender
        if sender is None:
            logger.warning(
                "[NagaSend] sender 不可用: trace=%s naga_id=%s bind_uuid=%s",
                trace_id,
                naga_id,
                bind_uuid,
            )
            return _json_error("sender not available", status=503)

        moderation: dict[str, Any]
        naga_cfg = getattr(cfg, "naga", None)
        moderation_enabled = bool(getattr(naga_cfg, "moderation_enabled", True))
        security = getattr(ctx.command_dispatcher, "security", None)
        if not moderation_enabled:
            moderation = {
                "status": "skipped_disabled",
                "blocked": False,
                "categories": [],
                "message": "Naga moderation disabled by config; message sent without moderation block",
                "model_name": "",
            }
            logger.warning(
                "[NagaSend] 审核已禁用，直接放行: trace=%s naga_id=%s bind_uuid=%s key=%s",
                trace_id,
                naga_id,
                bind_uuid,
                message_key,
            )
        elif security is None or not hasattr(security, "moderate_naga_message"):
            moderation = {
                "status": "error_allowed",
                "blocked": False,
                "categories": [],
                "message": "Naga moderation service unavailable; message sent without moderation block",
                "model_name": "",
            }
            logger.warning(
                "[NagaSend] 审核服务不可用，按允许发送: trace=%s naga_id=%s bind_uuid=%s",
                trace_id,
                naga_id,
                bind_uuid,
            )
        else:
            logger.info(
                "[NagaSend] 审核开始: trace=%s naga_id=%s bind_uuid=%s key=%s fmt=%s content_len=%s",
                trace_id,
                naga_id,
                bind_uuid,
                message_key,
                message_format,
                len(content),
            )
            result = await security.moderate_naga_message(
                message_format=message_format,
                content=content,
            )
            moderation = {
                "status": result.status,
                "blocked": result.blocked,
                "categories": result.categories,
                "message": result.message,
                "model_name": result.model_name,
            }
            logger.info(
                "[NagaSend] 审核完成: trace=%s naga_id=%s bind_uuid=%s key=%s blocked=%s status=%s model=%s categories=%s",
                trace_id,
                naga_id,
                bind_uuid,
                message_key,
                result.blocked,
                result.status,
                result.model_name,
                ",".join(result.categories) or "-",
            )
        if moderation["blocked"]:
            logger.warning(
                "[NagaSend] 审核拦截: trace=%s naga_id=%s bind_uuid=%s key=%s reason=%s",
                trace_id,
                naga_id,
                bind_uuid,
                message_key,
                moderation["message"],
            )
            return web.json_response(
                {
                    "ok": False,
                    "error": "message blocked by moderation",
                    "moderation": moderation,
                },
                status=403,
            )

        send_content: str | None = content if message_format == "text" else None
        image_path: str | None = None
        tmp_path: str | None = None
        rendered = False
        render_fallback = False
        if message_format in {"markdown", "html"}:
            import tempfile

            try:
                html_str = content
                if message_format == "markdown":
                    html_str = await render_markdown_to_html(content)
                fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="naga_send_")
                os.close(fd)
                await render_html_to_image(html_str, tmp_path)
                image_path = tmp_path
                rendered = True
                logger.info(
                    "[NagaSend] 富文本渲染成功: trace=%s naga_id=%s bind_uuid=%s key=%s fmt=%s image=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    message_format,
                    Path(tmp_path).name if tmp_path is not None else "",
                )
            except Exception as exc:
                logger.warning(
                    "[NagaSend] 渲染失败，回退文本发送: trace=%s naga_id=%s bind_uuid=%s key=%s err=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    exc,
                )
                send_content = content
                render_fallback = True

        sent_private = False
        sent_group = False
        group_policy_blocked = False

        async def _ensure_delivery_active() -> tuple[Any, Response | None]:
            current_binding, live_err = await naga_store.ensure_delivery_active(
                naga_id=naga_id,
                bind_uuid=bind_uuid,
            )
            if current_binding is None:
                logger.warning(
                    "[NagaSend] 投递中止: trace=%s naga_id=%s bind_uuid=%s key=%s reason=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    live_err.message
                    if live_err is not None
                    else "delivery no longer active",
                )
                return None, web.json_response(
                    {
                        "ok": False,
                        "error": (
                            live_err.message
                            if live_err is not None
                            else "delivery no longer active"
                        ),
                        "sent_private": sent_private,
                        "sent_group": sent_group,
                        "moderation": moderation,
                    },
                    status=live_err.http_status if live_err is not None else 409,
                )
            return current_binding, None

        try:
            cq_image: str | None = None
            if image_path is not None:
                file_uri = Path(image_path).resolve().as_uri()
                cq_image = f"[CQ:image,file={file_uri}]"

            if mode in {"private", "both"}:
                current_binding, abort_response = await _ensure_delivery_active()
                if abort_response is not None:
                    return abort_response
                logger.info(
                    "[NagaSend] 私聊投递开始: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    current_binding.qq_id,
                )
                try:
                    if send_content is not None:
                        await sender.send_private_message(
                            current_binding.qq_id, send_content
                        )
                    elif cq_image is not None:
                        await sender.send_private_message(
                            current_binding.qq_id, cq_image
                        )
                    sent_private = True
                    logger.info(
                        "[NagaSend] 私聊投递成功: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        current_binding.qq_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[NagaSend] 私聊发送失败: trace=%s naga_id=%s qq=%d key=%s err=%s",
                        trace_id,
                        naga_id,
                        current_binding.qq_id,
                        message_key,
                        exc,
                    )

            if mode in {"group", "both"}:
                current_binding, abort_response = await _ensure_delivery_active()
                if abort_response is not None:
                    return abort_response
                current_cfg = ctx.config_getter()
                if current_binding.group_id not in current_cfg.naga.allowed_groups:
                    group_policy_blocked = True
                    logger.warning(
                        "[NagaSend] 群投递被策略阻止: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        current_binding.group_id,
                    )
                else:
                    logger.info(
                        "[NagaSend] 群投递开始: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        current_binding.group_id,
                    )
                    try:
                        if send_content is not None:
                            await sender.send_group_message(
                                current_binding.group_id, send_content
                            )
                        elif cq_image is not None:
                            await sender.send_group_message(
                                current_binding.group_id, cq_image
                            )
                        sent_group = True
                        logger.info(
                            "[NagaSend] 群投递成功: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                            trace_id,
                            naga_id,
                            bind_uuid,
                            message_key,
                            current_binding.group_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "[NagaSend] 群聊发送失败: trace=%s naga_id=%s group=%d key=%s err=%s",
                            trace_id,
                            naga_id,
                            current_binding.group_id,
                            message_key,
                            exc,
                        )
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        if mode == "private" and not sent_private:
            return web.json_response(
                {
                    "ok": False,
                    "error": "private delivery failed",
                    "sent_private": sent_private,
                    "sent_group": sent_group,
                    "moderation": moderation,
                },
                status=502,
            )
        if mode == "group" and not sent_group:
            return web.json_response(
                {
                    "ok": False,
                    "error": "group delivery failed",
                    "sent_private": sent_private,
                    "sent_group": sent_group,
                    "moderation": moderation,
                },
                status=502,
            )
        if mode == "both" and not (sent_private or sent_group):
            if group_policy_blocked:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "bound group is not in naga.allowed_groups",
                        "sent_private": sent_private,
                        "sent_group": sent_group,
                        "moderation": moderation,
                    },
                    status=403,
                )
            return web.json_response(
                {
                    "ok": False,
                    "error": "all deliveries failed",
                    "sent_private": sent_private,
                    "sent_group": sent_group,
                    "moderation": moderation,
                },
                status=502,
            )

        await naga_store.record_usage(naga_id, bind_uuid=bind_uuid)
        partial_success = mode == "both" and (sent_private != sent_group)
        logger.info(
            "[NagaSend] 请求完成: trace=%s naga_id=%s bind_uuid=%s key=%s sent_private=%s sent_group=%s partial=%s rendered=%s fallback=%s",
            trace_id,
            naga_id,
            bind_uuid,
            message_key,
            sent_private,
            sent_group,
            partial_success,
            rendered,
            render_fallback,
        )
        return web.json_response(
            {
                "ok": True,
                "naga_id": naga_id,
                "bind_uuid": bind_uuid,
                "sent_private": sent_private,
                "sent_group": sent_group,
                "partial_success": partial_success,
                "delivery_status": (
                    "partial_success" if partial_success else "full_success"
                ),
                "rendered": rendered,
                "render_fallback": render_fallback,
                "moderation": moderation,
            }
        )
    finally:
        await naga_store.release_delivery(bind_uuid=bind_uuid)


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
