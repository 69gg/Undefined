from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Literal
from uuid import uuid4

from aiohttp import ClientSession, ClientTimeout

from Undefined.api.naga_store import NagaBinding, NagaStore, PendingBinding
from Undefined.services.commands.context import CommandContext

from .policy import is_naga_command_visible

logger = logging.getLogger(__name__)

_SCOPES_FILE = Path(__file__).parent / "scopes.json"


def _load_scopes_sync() -> dict[str, str]:
    try:
        with open(_SCOPES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


async def _load_scopes() -> dict[str, str]:
    return await asyncio.to_thread(_load_scopes_sync)


_SCOPE_ALIASES: dict[str, str] = {
    "admin_only": "admin",
    "superadmin_only": "superadmin",
}


async def _check_scope(
    subcmd: str, sender_id: int, context: CommandContext
) -> str | None:
    scopes = await _load_scopes()
    raw = scopes.get(subcmd, "superadmin")
    scope = _SCOPE_ALIASES.get(raw, raw)

    if scope == "group_only":
        if context.scope != "group":
            return "该子命令仅限群聊使用"
        return None
    if scope == "private_only":
        if context.scope != "private":
            return "该子命令仅限私聊使用"
        return None
    if scope == "public":
        return None
    if scope == "superadmin" and context.config.is_superadmin(sender_id):
        return None
    if scope == "admin" and (
        context.config.is_admin(sender_id) or context.config.is_superadmin(sender_id)
    ):
        return None
    return "权限不足"


async def _reply(context: CommandContext, text: str) -> None:
    if context.scope == "private" and context.user_id is not None:
        await context.sender.send_private_message(context.user_id, text)
    elif context.group_id:
        await context.sender.send_group_message(context.group_id, text)


async def _notify_user(context: CommandContext, user_id: int, text: str) -> None:
    real_sender = getattr(context.dispatcher, "sender", context.sender)
    await real_sender.send_private_message(user_id, text)


def _naga_store(context: CommandContext) -> NagaStore | None:
    store = getattr(context.dispatcher, "naga_store", None)
    return store if isinstance(store, NagaStore) else None


def _remote_ready(context: CommandContext) -> str | None:
    if not context.config.naga.api_url:
        return "❌ naga.api_url 未配置"
    if not context.config.naga.api_key:
        return "❌ naga.api_key 未配置"
    return None


async def _build_request_context(
    naga_id: str, context: CommandContext
) -> dict[str, object]:
    payload: dict[str, object] = {
        "naga_id": naga_id,
        "sender_id": context.sender_id,
        "group_id": context.group_id,
        "scope": context.scope,
        "bot_qq": context.config.bot_qq,
    }

    onebot = getattr(context, "onebot", None)
    if onebot is None:
        return payload

    try:
        group_info = await onebot.get_group_info(context.group_id)
    except Exception:
        group_info = None
    if isinstance(group_info, dict):
        group_data = group_info.get("data", group_info)
        if isinstance(group_data, dict):
            group_name = str(group_data.get("group_name", "") or "").strip()
            if group_name:
                payload["group_name"] = group_name

    try:
        user_info = await onebot.get_stranger_info(context.sender_id)
    except Exception:
        user_info = None
    if isinstance(user_info, dict):
        user_data = user_info.get("data", user_info)
        if isinstance(user_data, dict):
            nickname = str(user_data.get("nickname", "") or "").strip()
            if nickname:
                payload["sender_nickname"] = nickname
            card = str(user_data.get("remark", "") or "").strip()
            if card:
                payload["sender_remark"] = card

    return payload


async def execute(args: list[str], context: CommandContext) -> None:
    trace_id = uuid4().hex[:8]
    logger.info(
        "[NagaCmd] 开始: trace=%s scope=%s sender=%s group=%s user=%s args=%s",
        trace_id,
        context.scope,
        context.sender_id,
        context.group_id,
        context.user_id,
        args,
    )
    if not is_naga_command_visible(context):
        logger.info(
            "[NagaCmd] 忽略不可见命令: trace=%s scope=%s sender=%s group=%s",
            trace_id,
            context.scope,
            context.sender_id,
            context.group_id,
        )
        return

    if not context.config.nagaagent_mode_enabled or not context.config.naga.enabled:
        logger.warning("[NagaCmd] 集成未启用: trace=%s", trace_id)
        await _reply(context, "Naga 集成未启用")
        return

    if not args:
        await _reply(
            context,
            "用法: /naga <bind|unbind> [参数]\n"
            "子命令:\n"
            "  bind <naga_id> — 在白名单群聊中发起绑定\n"
            "  unbind <naga_id> — 超管解绑并吊销签名",
        )
        return

    subcmd = args[0].lower()
    sub_args = args[1:]
    logger.info(
        "[NagaCmd] 子命令解析: trace=%s subcmd=%s sub_args=%s",
        trace_id,
        subcmd,
        sub_args,
    )
    perm_err = await _check_scope(subcmd, context.sender_id, context)
    if perm_err is not None:
        logger.warning(
            "[NagaCmd] 权限/作用域拒绝: trace=%s subcmd=%s err=%s",
            trace_id,
            subcmd,
            perm_err,
        )
        await _reply(context, f"❌ {perm_err}")
        return

    store = _naga_store(context)
    if store is None:
        logger.error(
            "[NagaCmd] NagaStore 未初始化: trace=%s subcmd=%s", trace_id, subcmd
        )
        await _reply(context, "❌ NagaStore 未初始化")
        return

    handlers: dict[str, object] = {
        "bind": _handle_bind,
        "unbind": _handle_unbind,
    }
    handler = handlers.get(subcmd)
    if handler is None:
        logger.warning("[NagaCmd] 未知子命令: trace=%s subcmd=%s", trace_id, subcmd)
        await _reply(context, f"❌ 未知子命令: {subcmd}")
        return

    try:
        logger.info("[NagaCmd] 开始执行: trace=%s subcmd=%s", trace_id, subcmd)
        await handler(sub_args, context, store)  # type: ignore[operator]
        logger.info("[NagaCmd] 执行完成: trace=%s subcmd=%s", trace_id, subcmd)
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("[NagaCmd] %s 执行失败: error_id=%s", subcmd, error_id)
        await _reply(context, f"❌ 操作失败（错误码: {error_id}）: {exc}")


async def _handle_bind(
    args: list[str], context: CommandContext, naga_store: NagaStore
) -> None:
    logger.info(
        "[NagaCmd] bind 请求: sender=%s group=%s args=%s",
        context.sender_id,
        context.group_id,
        args,
    )
    if context.scope != "group":
        await _reply(context, "❌ bind 命令仅限群聊中使用")
        return
    if not args:
        await _reply(context, "用法: /naga bind <naga_id>")
        return

    remote_err = _remote_ready(context)
    if remote_err is not None:
        await _reply(context, remote_err)
        return

    naga_id = args[0].strip()
    if not naga_id:
        await _reply(context, "❌ naga_id 不能为空")
        return

    request_context = await _build_request_context(naga_id, context)
    ok, msg, pending = await naga_store.submit_binding(
        naga_id=naga_id,
        qq_id=context.sender_id,
        group_id=context.group_id,
        request_context=request_context,
    )
    logger.info(
        "[NagaCmd] bind 本地登记结果: naga_id=%s ok=%s msg=%s bind_uuid=%s",
        naga_id,
        ok,
        msg,
        pending.bind_uuid if pending is not None else "",
    )
    if not ok or pending is None:
        await _reply(context, f"❌ {msg}")
        return

    pending, should_submit = await naga_store.begin_remote_submit(
        naga_id,
        bind_uuid=pending.bind_uuid,
    )
    logger.info(
        "[NagaCmd] bind 远端提交判定: naga_id=%s bind_uuid=%s should_submit=%s",
        naga_id,
        pending.bind_uuid if pending is not None else "",
        should_submit,
    )
    if pending is None:
        await _reply(context, "❌ 绑定状态已变化，请重新发起 /naga bind")
        return

    is_existing = "已存在" in msg
    if not should_submit:
        prefix = "ℹ️" if is_existing else "✅"
        await _reply(
            context,
            f"{prefix} {msg}\nnaga_id: {naga_id}\n绑定请求已在处理中，请等待远端确认",
        )
        return

    submit_status, detail = await _submit_bind_request_to_naga(context, pending)
    logger.info(
        "[NagaCmd] bind 远端提交完成: naga_id=%s bind_uuid=%s status=%s detail=%s",
        naga_id,
        pending.bind_uuid,
        submit_status,
        detail,
    )
    if submit_status == "accepted":
        verb = "已重新发送" if is_existing else "已发送"
        await _reply(
            context,
            f"✅ {msg}\nnaga_id: {naga_id}\n绑定请求{verb}到 Naga 端，等待确认",
        )
        return

    await _reply(
        context,
        "⚠️ 绑定申请已保留在本地，但未确认远端是否已接收\n"
        f"naga_id: {naga_id}\n"
        f"bind_uuid: {pending.bind_uuid}\n"
        f"原因: {detail}\n"
        "稍后重复执行同一个 /naga bind，会沿用这次申请继续重试",
    )


async def _handle_unbind(
    args: list[str], context: CommandContext, naga_store: NagaStore
) -> None:
    logger.info(
        "[NagaCmd] unbind 请求: sender=%s scope=%s args=%s",
        context.sender_id,
        context.scope,
        args,
    )
    if not args:
        await _reply(context, "用法: /naga unbind <naga_id>")
        return

    naga_id = args[0].strip()
    binding, changed, err = await naga_store.revoke_binding(naga_id)
    logger.info(
        "[NagaCmd] unbind 本地吊销结果: naga_id=%s found=%s changed=%s err=%s",
        naga_id,
        binding is not None,
        changed,
        err.message if err is not None else "",
    )
    if binding is None:
        detail = (
            err.message if err is not None else f"未找到 naga_id '{naga_id}' 的绑定"
        )
        await _reply(context, f"❌ {detail}")
        return
    if not changed:
        await _reply(context, f"ℹ️ naga_id '{naga_id}' 已处于解绑状态")
        return

    remote_synced = await _notify_remote_revoke(context, binding)
    await _reply(
        context,
        f"✅ 已解绑 naga_id '{naga_id}'\n"
        f"远端吊销同步: {'成功' if remote_synced else '失败（需远端手动处理）'}",
    )

    try:
        await _notify_user(
            context,
            binding.qq_id,
            f"🔒 你的 Naga 绑定已被解除\nnaga_id: {naga_id}",
        )
    except Exception as exc:
        logger.warning("[NagaCmd] 通知解绑失败: %s", exc)


async def _submit_bind_request_to_naga(
    context: CommandContext, pending: PendingBinding
) -> tuple[Literal["accepted", "remote_error", "transport_error"], str]:
    url = f"{context.config.naga.api_url.rstrip('/')}/api/integration/bind/request"
    headers = {
        "Authorization": f"Bearer {context.config.naga.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "bind_uuid": pending.bind_uuid,
        "naga_id": pending.naga_id,
        "request_context": pending.request_context,
    }
    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status < 300:
                    logger.info(
                        "[NagaCmd] 绑定请求已提交: naga_id=%s bind_uuid=%s status=%d",
                        pending.naga_id,
                        pending.bind_uuid,
                        resp.status,
                    )
                    return "accepted", f"HTTP {resp.status}"
                body = await resp.text()
                logger.warning(
                    "[NagaCmd] 绑定请求失败: naga_id=%s bind_uuid=%s status=%d body=%s",
                    pending.naga_id,
                    pending.bind_uuid,
                    resp.status,
                    body[:200],
                )
                detail = body[:200].strip() or f"HTTP {resp.status}"
                return "remote_error", detail
    except Exception as exc:
        logger.warning(
            "[NagaCmd] 绑定请求异常: naga_id=%s bind_uuid=%s err=%s",
            pending.naga_id,
            pending.bind_uuid,
            exc,
        )
        return "transport_error", str(exc) or exc.__class__.__name__


async def _notify_remote_revoke(context: CommandContext, binding: NagaBinding) -> bool:
    remote_err = _remote_ready(context)
    if remote_err is not None:
        logger.warning("[NagaCmd] 远端吊销同步跳过: %s", remote_err)
        return False

    url = f"{context.config.naga.api_url.rstrip('/')}/api/integration/bind/revoke"
    headers = {
        "Authorization": f"Bearer {context.config.naga.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "bind_uuid": binding.bind_uuid,
        "naga_id": binding.naga_id,
    }
    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status < 300:
                    logger.info(
                        "[NagaCmd] 远端吊销同步成功: naga_id=%s bind_uuid=%s status=%d",
                        binding.naga_id,
                        binding.bind_uuid,
                        resp.status,
                    )
                    return True
                body = await resp.text()
                logger.warning(
                    "[NagaCmd] 远端吊销同步失败: naga_id=%s bind_uuid=%s status=%d body=%s",
                    binding.naga_id,
                    binding.bind_uuid,
                    resp.status,
                    body[:200],
                )
                return False
    except Exception as exc:
        logger.warning(
            "[NagaCmd] 远端吊销同步异常: naga_id=%s bind_uuid=%s err=%s",
            binding.naga_id,
            binding.bind_uuid,
            exc,
        )
        return False
