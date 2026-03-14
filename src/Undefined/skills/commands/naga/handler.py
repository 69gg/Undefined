from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from aiohttp import ClientSession, ClientTimeout

from Undefined.api.naga_store import mask_token
from Undefined.services.commands.context import CommandContext

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
    """检查子命令权限与作用域，返回错误提示或 None 表示通过。

    支持的 scope 值:
      - ``public``          — 任何人、任何场景
      - ``admin`` / ``admin_only``        — 仅管理员+
      - ``superadmin`` / ``superadmin_only`` — 仅超级管理员
      - ``group_only``      — 任何人，但仅限群聊
      - ``private_only``    — 任何人，但仅限私聊
    """
    scopes = await _load_scopes()
    raw = scopes.get(subcmd, "superadmin")
    scope = _SCOPE_ALIASES.get(raw, raw)

    # 作用域限制
    if scope == "group_only":
        if context.scope != "group":
            return "该子命令仅限群聊使用"
        return None
    if scope == "private_only":
        if context.scope != "private":
            return "该子命令仅限私聊使用"
        return None

    # 权限检查
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
    """根据 scope 发送回复"""
    if context.scope == "private" and context.user_id is not None:
        await context.sender.send_private_message(context.user_id, text)
    elif context.group_id:
        await context.sender.send_group_message(context.group_id, text)


async def _notify_user(context: CommandContext, user_id: int, text: str) -> None:
    """直接私聊通知指定用户（绕过私聊代理，确保消息发给目标用户而非命令调用者）"""
    real_sender = getattr(context.dispatcher, "sender", context.sender)
    await real_sender.send_private_message(user_id, text)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /naga 命令"""
    # 前置检查: 需同时开启 nagaagent_mode_enabled（总开关）和 naga.enabled（网关子开关）
    if not context.config.nagaagent_mode_enabled or not context.config.naga.enabled:
        await _reply(context, "Naga 集成未启用")
        return

    if not args:
        await _reply(
            context,
            "用法: /naga <bind|approve|reject|revoke|list|pending|info> [参数]\n"
            "子命令:\n"
            "  bind <naga_id> — 提交绑定申请（群聊内使用）\n"
            "  approve <naga_id> — 通过绑定申请\n"
            "  reject <naga_id> — 拒绝绑定申请\n"
            "  revoke <naga_id> — 吊销已有绑定\n"
            "  list — 列出所有活跃绑定\n"
            "  pending — 列出待审核申请\n"
            "  info <naga_id> — 查看绑定详情",
        )
        return

    subcmd = args[0].lower()
    sub_args = args[1:]

    # 权限检查
    perm_err = await _check_scope(subcmd, context.sender_id, context)
    if perm_err is not None:
        await _reply(context, f"❌ {perm_err}")
        return

    # 群聊白名单检查：群聊场景下仅在 allowed_groups 内的群可用
    if context.scope == "group":
        if context.group_id not in context.config.naga.allowed_groups:
            return

    naga_store = getattr(context.dispatcher, "naga_store", None)
    if naga_store is None:
        await _reply(context, "❌ NagaStore 未初始化")
        return

    handlers: dict[str, object] = {
        "bind": _handle_bind,
        "approve": _handle_approve,
        "reject": _handle_reject,
        "revoke": _handle_revoke,
        "list": _handle_list,
        "pending": _handle_pending,
        "info": _handle_info,
    }

    handler = handlers.get(subcmd)
    if handler is None:
        await _reply(context, f"❌ 未知子命令: {subcmd}")
        return

    try:
        await handler(sub_args, context, naga_store)  # type: ignore[operator]
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("[NagaCmd] %s 执行失败: error_id=%s", subcmd, error_id)
        await _reply(context, f"❌ 操作失败（错误码: {error_id}）: {exc}")


async def _handle_bind(
    args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga bind <naga_id>"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    if context.scope != "group":
        await _reply(context, "❌ bind 命令仅限群聊中使用")
        return

    if not args:
        await _reply(context, "用法: /naga bind <naga_id>")
        return

    naga_id = args[0].strip()
    if not naga_id:
        await _reply(context, "❌ naga_id 不能为空")
        return

    ok, msg = await naga_store.submit_binding(
        naga_id=naga_id,
        qq_id=context.sender_id,
        group_id=context.group_id,
    )

    if not ok:
        await _reply(context, f"❌ {msg}")
        return

    await _reply(context, f"✅ {msg}")

    # 私聊通知超管
    superadmin_qq = context.config.superadmin_qq
    if superadmin_qq:
        try:
            await _notify_user(
                context,
                superadmin_qq,
                f"📋 Naga 绑定申请\n"
                f"naga_id: {naga_id}\n"
                f"申请人 QQ: {context.sender_id}\n"
                f"来源群: {context.group_id}\n"
                f"使用 /naga approve {naga_id} 或 /naga reject {naga_id} 处理",
            )
        except Exception as exc:
            logger.warning("[NagaCmd] 通知超管失败: %s", exc)


async def _handle_approve(
    args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga approve <naga_id>"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    if not args:
        await _reply(context, "用法: /naga approve <naga_id>")
        return

    naga_id = args[0].strip()
    binding = await naga_store.approve(naga_id)
    if binding is None:
        await _reply(context, f"❌ 未找到 naga_id '{naga_id}' 的待审核申请")
        return

    # 调 Naga API 同步 token
    sync_ok = await _sync_token_to_naga(context, naga_id, binding.token)

    await _reply(
        context,
        f"✅ 绑定已通过\n"
        f"naga_id: {naga_id}\n"
        f"QQ: {binding.qq_id}\n"
        f"群: {binding.group_id}\n"
        f"Token: {mask_token(binding.token)}\n"
        f"Naga 同步: {'成功' if sync_ok else '失败（请手动同步）'}",
    )

    # 私聊通知申请人（绕过代理，确保发给申请人而非调用者）
    try:
        await _notify_user(
            context,
            binding.qq_id,
            f"🎉 你的 Naga 绑定申请已通过！\nnaga_id: {naga_id}",
        )
    except Exception as exc:
        logger.warning("[NagaCmd] 通知申请人失败: %s", exc)


async def _handle_reject(
    args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga reject <naga_id>"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    if not args:
        await _reply(context, "用法: /naga reject <naga_id>")
        return

    naga_id = args[0].strip()

    # 获取 pending 信息以通知申请人
    pending_list = naga_store.list_pending()
    pending_qq: int | None = None
    for p in pending_list:
        if p.naga_id == naga_id:
            pending_qq = p.qq_id
            break

    ok = await naga_store.reject(naga_id)
    if not ok:
        await _reply(context, f"❌ 未找到 naga_id '{naga_id}' 的待审核申请")
        return

    await _reply(context, f"✅ 已拒绝 naga_id '{naga_id}' 的绑定申请")

    # 私聊通知申请人（绕过代理，确保发给申请人而非调用者）
    if pending_qq:
        try:
            await _notify_user(
                context,
                pending_qq,
                f"❌ 你的 Naga 绑定申请已被拒绝\nnaga_id: {naga_id}",
            )
        except Exception as exc:
            logger.warning("[NagaCmd] 通知申请人失败: %s", exc)


async def _handle_revoke(
    args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga revoke <naga_id>"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    if not args:
        await _reply(context, "用法: /naga revoke <naga_id>")
        return

    naga_id = args[0].strip()

    # 获取绑定信息用于通知和 API 调用
    binding = naga_store.get_binding(naga_id)
    if binding is None:
        await _reply(context, f"❌ 未找到 naga_id '{naga_id}' 的绑定")
        return

    ok = await naga_store.revoke(naga_id)
    if not ok:
        await _reply(context, f"❌ naga_id '{naga_id}' 已被吊销或不存在")
        return

    # 调 Naga API 删除 token
    delete_ok = await _delete_token_from_naga(context, naga_id)

    await _reply(
        context,
        f"✅ 已吊销 naga_id '{naga_id}' 的绑定\n"
        f"Naga 同步删除: {'成功' if delete_ok else '失败（请手动处理）'}",
    )


async def _handle_list(
    _args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga list"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    bindings = naga_store.list_bindings()
    if not bindings:
        await _reply(context, "📋 当前没有活跃绑定")
        return

    lines = ["📋 活跃绑定列表:"]
    for b in bindings:
        lines.append(
            f"  • {b.naga_id} → QQ:{b.qq_id} 群:{b.group_id} 使用:{b.use_count}次"
        )
    await _reply(context, "\n".join(lines))


async def _handle_pending(
    _args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga pending"""
    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    pending = naga_store.list_pending()
    if not pending:
        await _reply(context, "📋 当前没有待审核申请")
        return

    lines = ["📋 待审核申请:"]
    for p in pending:
        lines.append(f"  • {p.naga_id} ← QQ:{p.qq_id} 群:{p.group_id}")
    await _reply(context, "\n".join(lines))


async def _handle_info(
    args: list[str], context: CommandContext, naga_store: object
) -> None:
    """处理 /naga info <naga_id>"""
    from datetime import datetime

    from Undefined.api.naga_store import NagaStore

    assert isinstance(naga_store, NagaStore)

    if not args:
        await _reply(context, "用法: /naga info <naga_id>")
        return

    naga_id = args[0].strip()
    binding = naga_store.get_binding(naga_id)
    if binding is None:
        await _reply(context, f"❌ 未找到 naga_id '{naga_id}' 的绑定")
        return

    created = datetime.fromtimestamp(binding.created_at).strftime("%Y-%m-%d %H:%M:%S")
    last_used = (
        datetime.fromtimestamp(binding.last_used_at).strftime("%Y-%m-%d %H:%M:%S")
        if binding.last_used_at
        else "从未使用"
    )

    await _reply(
        context,
        f"📋 绑定详情: {naga_id}\n"
        f"Token: {mask_token(binding.token)}\n"
        f"QQ: {binding.qq_id}\n"
        f"群: {binding.group_id}\n"
        f"状态: {'已吊销' if binding.revoked else '活跃'}\n"
        f"创建时间: {created}\n"
        f"最后使用: {last_used}\n"
        f"使用次数: {binding.use_count}",
    )


async def _sync_token_to_naga(
    context: CommandContext, naga_id: str, token: str
) -> bool:
    """调 Naga API 同步 token"""
    api_url = context.config.naga.api_url
    api_key = context.config.naga.api_key
    if not api_url:
        logger.warning("[NagaCmd] naga.api_url 未配置，跳过 token 同步")
        return False

    url = f"{api_url.rstrip('/')}/api/integration/tokens"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={"naga_id": naga_id, "token": token},
                headers=headers,
            ) as resp:
                if resp.status < 300:
                    logger.info(
                        "[NagaCmd] Token 同步成功: naga_id=%s status=%d",
                        naga_id,
                        resp.status,
                    )
                    return True
                body = await resp.text()
                logger.warning(
                    "[NagaCmd] Token 同步失败: naga_id=%s status=%d body=%s",
                    naga_id,
                    resp.status,
                    body[:200],
                )
                return False
    except Exception as exc:
        logger.warning(
            "[NagaCmd] Token 同步请求失败: naga_id=%s error=%s", naga_id, exc
        )
        return False


async def _delete_token_from_naga(context: CommandContext, naga_id: str) -> bool:
    """调 Naga API 删除 token"""
    api_url = context.config.naga.api_url
    api_key = context.config.naga.api_key
    if not api_url:
        logger.warning("[NagaCmd] naga.api_url 未配置，跳过 token 删除")
        return False

    url = f"{api_url.rstrip('/')}/api/integration/tokens/{naga_id}"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.delete(url, headers=headers) as resp:
                if resp.status < 300:
                    logger.info(
                        "[NagaCmd] Token 删除成功: naga_id=%s status=%d",
                        naga_id,
                        resp.status,
                    )
                    return True
                logger.warning(
                    "[NagaCmd] Token 删除失败: naga_id=%s status=%d",
                    naga_id,
                    resp.status,
                )
                return False
    except Exception as exc:
        logger.warning(
            "[NagaCmd] Token 删除请求失败: naga_id=%s error=%s", naga_id, exc
        )
        return False
