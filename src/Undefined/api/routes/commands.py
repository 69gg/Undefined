"""Slash command metadata route handlers for the Runtime API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, cast

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _VIRTUAL_USER_ID, _json_error, _to_bool
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, SubcommandMeta

logger = logging.getLogger(__name__)

_DEFAULT_COMMAND_SCOPE = "webui"
_VALID_COMMAND_SCOPES = frozenset({"webui", "private", "group"})


@dataclass(frozen=True)
class _CommandRequestContext:
    command_context: CommandContext
    api_scope: str
    execution_scope: str
    sender_id: int
    user_id: int | None
    group_id: int


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_is_superadmin(config: Any, sender_id: int) -> bool:
    checker = getattr(config, "is_superadmin", None)
    if callable(checker):
        return bool(checker(sender_id))
    return sender_id == _coerce_int(getattr(config, "superadmin_qq", 0), 0)


def _config_is_admin(config: Any, sender_id: int) -> bool:
    checker = getattr(config, "is_admin", None)
    if callable(checker):
        return bool(checker(sender_id))
    admin_qqs = getattr(config, "admin_qqs", []) or []
    return sender_id in {_coerce_int(item, 0) for item in admin_qqs}


def _check_permission(config: Any, permission: str, sender_id: int) -> bool:
    normalized = str(permission or "public").strip().lower()
    if normalized == "superadmin":
        return _config_is_superadmin(config, sender_id)
    if normalized == "admin":
        return _config_is_admin(config, sender_id) or _config_is_superadmin(
            config, sender_id
        )
    return True


def _permission_label(permission: str) -> str:
    normalized = str(permission or "public").strip().lower()
    if normalized == "superadmin":
        return "superadmin"
    if normalized == "admin":
        return "admin"
    return "public"


def _availability_reason(
    *,
    scope: str,
    allow_in_private: bool,
    permission: str,
    permission_allowed: bool,
    policy_visible: bool,
) -> str | None:
    if not policy_visible:
        return "policy_hidden"
    if scope == "private" and not allow_in_private:
        return "private_not_allowed"
    if not permission_allowed:
        return f"requires_{_permission_label(permission)}"
    return None


def _build_command_request_context(
    ctx: RuntimeAPIContext, request: web.Request
) -> _CommandRequestContext:
    cfg = ctx.config_getter()
    raw_scope = str(request.query.get("scope", _DEFAULT_COMMAND_SCOPE) or "").lower()
    api_scope = (
        raw_scope if raw_scope in _VALID_COMMAND_SCOPES else _DEFAULT_COMMAND_SCOPE
    )

    if api_scope == "webui":
        execution_scope = "private"
        sender_id = _coerce_int(getattr(cfg, "superadmin_qq", 0), 0)
        user_id: int | None = _VIRTUAL_USER_ID
        group_id = 0
        is_webui_session = True
    elif api_scope == "private":
        execution_scope = "private"
        sender_id = _coerce_int(
            request.query.get("sender_id"),
            _coerce_int(getattr(cfg, "superadmin_qq", 0), 0),
        )
        user_id = _coerce_int(request.query.get("user_id"), sender_id)
        group_id = 0
        is_webui_session = False
    else:
        execution_scope = "group"
        sender_id = _coerce_int(
            request.query.get("sender_id"),
            _coerce_int(getattr(cfg, "superadmin_qq", 0), 0),
        )
        user_id = None
        group_id = _coerce_int(request.query.get("group_id"), 0)
        is_webui_session = False

    dispatcher = ctx.command_dispatcher
    command_registry = getattr(dispatcher, "command_registry", None)
    if command_registry is None:
        raise RuntimeError("command registry is unavailable")
    command_context = CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=cfg,
        sender=cast(Any, getattr(dispatcher, "sender", ctx.sender)),
        ai=getattr(dispatcher, "ai", ctx.ai),
        faq_storage=cast(Any, getattr(dispatcher, "faq_storage", None)),
        onebot=cast(Any, getattr(dispatcher, "onebot", ctx.onebot)),
        security=cast(Any, getattr(dispatcher, "security", None)),
        queue_manager=getattr(dispatcher, "queue_manager", ctx.queue_manager),
        rate_limiter=getattr(dispatcher, "rate_limiter", None),
        dispatcher=dispatcher,
        registry=command_registry,
        scope=execution_scope,
        user_id=user_id,
        is_webui_session=is_webui_session,
        cognitive_service=getattr(ctx, "cognitive_service", None),
        history_manager=ctx.history_manager,
    )
    return _CommandRequestContext(
        command_context=command_context,
        api_scope=api_scope,
        execution_scope=execution_scope,
        sender_id=sender_id,
        user_id=user_id,
        group_id=group_id,
    )


def _subcommand_usage(command: CommandMeta, subcommand: SubcommandMeta) -> str:
    args = str(subcommand.args or "").strip()
    return f"/{command.name} {subcommand.name}{f' {args}' if args else ''}"


def _serialize_subcommand(
    command: CommandMeta,
    subcommand: SubcommandMeta,
    *,
    request_context: _CommandRequestContext,
    policy_visible: bool,
) -> dict[str, Any]:
    scope = request_context.execution_scope
    permission_allowed = _check_permission(
        request_context.command_context.config,
        subcommand.permission,
        request_context.sender_id,
    )
    unavailable_reason = _availability_reason(
        scope=scope,
        allow_in_private=subcommand.allow_in_private,
        permission=subcommand.permission,
        permission_allowed=permission_allowed,
        policy_visible=policy_visible,
    )
    return {
        "name": subcommand.name,
        "trigger": f"/{command.name} {subcommand.name}",
        "description": subcommand.description,
        "args": subcommand.args,
        "usage": _subcommand_usage(command, subcommand),
        "permission": subcommand.permission,
        "allow_in_private": subcommand.allow_in_private,
        "available": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
    }


def _serialize_inference(command: CommandMeta) -> dict[str, Any] | None:
    inference = command.inference
    if inference is None:
        return None
    return {
        "default": inference.default,
        "fallback": inference.fallback,
        "rules": [
            {"pattern": rule.pattern.pattern, "subcommand": rule.subcommand}
            for rule in inference.rules
        ],
    }


def _serialize_command(
    command: CommandMeta,
    *,
    request_context: _CommandRequestContext,
    include_unavailable: bool,
) -> dict[str, Any]:
    registry = request_context.command_context.registry
    policy_visible = True
    if registry is not None:
        policy_visible = bool(
            registry.is_visible(command, request_context.command_context)
        )

    permission_allowed = _check_permission(
        request_context.command_context.config,
        command.permission,
        request_context.sender_id,
    )
    unavailable_reason = _availability_reason(
        scope=request_context.execution_scope,
        allow_in_private=command.allow_in_private,
        permission=command.permission,
        permission_allowed=permission_allowed,
        policy_visible=policy_visible,
    )
    subcommands = [
        _serialize_subcommand(
            command,
            subcommand,
            request_context=request_context,
            policy_visible=policy_visible,
        )
        for subcommand in sorted(
            command.subcommands.values(), key=lambda item: item.name
        )
    ]
    if not include_unavailable:
        subcommands = [item for item in subcommands if bool(item.get("available"))]
    return {
        "name": command.name,
        "trigger": f"/{command.name}",
        "description": command.description,
        "usage": command.usage,
        "example": command.example,
        "permission": command.permission,
        "allow_in_private": command.allow_in_private,
        "show_in_help": command.show_in_help,
        "order": command.order,
        "aliases": list(command.aliases),
        "alias_triggers": [f"/{alias}" for alias in command.aliases],
        "subcommands": subcommands,
        "inference": _serialize_inference(command),
        "available": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
    }


def _matches_query(command: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystacks = [
        command.get("name"),
        command.get("description"),
        command.get("usage"),
        *(command.get("aliases") or []),
    ]
    for subcommand in command.get("subcommands") or []:
        haystacks.extend(
            [
                subcommand.get("name"),
                subcommand.get("description"),
                subcommand.get("args"),
                subcommand.get("usage"),
            ]
        )
    return any(query in str(item or "").lower() for item in haystacks)


def _build_commands_payload(
    ctx: RuntimeAPIContext,
    request: web.Request,
    *,
    command_name: str | None = None,
) -> dict[str, Any] | None:
    dispatcher = ctx.command_dispatcher
    registry = getattr(dispatcher, "command_registry", None)
    if registry is None:
        return {
            "scope": _DEFAULT_COMMAND_SCOPE,
            "commands": [],
            "count": 0,
            "total": 0,
        }

    include_hidden = _to_bool(request.query.get("include_hidden"))
    include_unavailable = _to_bool(request.query.get("include_unavailable"))
    request_context = _build_command_request_context(ctx, request)

    if command_name is not None:
        command = registry.resolve(command_name)
        if command is None:
            return None
        commands = [command]
    else:
        commands = registry.list_commands(include_hidden=include_hidden)

    serialized: list[dict[str, Any]] = []
    for command in commands:
        if not include_hidden and not command.show_in_help:
            continue
        item = _serialize_command(
            command,
            request_context=request_context,
            include_unavailable=include_unavailable,
        )
        has_available_subcommand = any(
            bool(subcommand.get("available"))
            for subcommand in item.get("subcommands") or []
        )
        if (
            not include_unavailable
            and not item["available"]
            and not has_available_subcommand
        ):
            continue
        serialized.append(item)

    query = str(request.query.get("q", "") or "").strip().lower()
    if query:
        serialized = [item for item in serialized if _matches_query(item, query)]

    total_aliases = sum(len(item.get("aliases") or []) for item in serialized)
    total_subcommands = sum(len(item.get("subcommands") or []) for item in serialized)
    payload = {
        "scope": request_context.api_scope,
        "execution_scope": request_context.execution_scope,
        "sender_id": request_context.sender_id,
        "user_id": request_context.user_id,
        "group_id": request_context.group_id,
        "commands": serialized,
        "count": len(serialized),
        "total": len(serialized),
        "aliases": total_aliases,
        "subcommands": total_subcommands,
    }
    if command_name is not None:
        if not serialized:
            return None
        payload["command"] = serialized[0]
        payload["requested_name"] = command_name
    return payload


async def commands_list_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    payload = _build_commands_payload(ctx, request)
    if payload is None:
        return _json_error("Missing or invalid commands payload", status=400)
    logger.info(
        "[RuntimeAPI][Commands] 列出命令: scope=%s count=%s",
        payload.get("scope"),
        payload.get("count"),
    )
    return web.json_response(payload)


async def command_detail_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    command_name = str(request.match_info.get("command_name", "") or "").strip().lower()
    if not command_name:
        return _json_error("command_name is required", status=400)
    payload = _build_commands_payload(ctx, request, command_name=command_name)
    if payload is None:
        return _json_error("Command not found", status=404)
    logger.info(
        "[RuntimeAPI][Commands] 命令详情: requested=%s canonical=%s scope=%s",
        command_name,
        payload["command"].get("name"),
        payload.get("scope"),
    )
    return web.json_response(payload)
