"""Tools route handlers for the Runtime API."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid as _uuid
from typing import Any, Awaitable

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _ToolInvokeExecutionTimeoutError,
    _json_error,
    _mask_url,
    _to_bool,
    _validate_callback_url,
)
from Undefined.context import RequestContext

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------


def get_filtered_tools(ctx: RuntimeAPIContext) -> list[dict[str, Any]]:
    """按配置过滤可用工具，返回 OpenAI function calling schema 列表。"""
    cfg = ctx.config_getter()
    api_cfg = cfg.api
    ai = ctx.ai
    if ai is None:
        return []

    tool_reg = getattr(ai, "tool_registry", None)
    agent_reg = getattr(ai, "agent_registry", None)

    all_schemas: list[dict[str, Any]] = []
    if tool_reg is not None:
        all_schemas.extend(tool_reg.get_tools_schema())

    # 收集 agent schema 并缓存名称集合（避免重复调用）
    agent_names: set[str] = set()
    if agent_reg is not None:
        agent_schemas = agent_reg.get_agents_schema()
        all_schemas.extend(agent_schemas)
        for schema in agent_schemas:
            func = schema.get("function", {})
            name = str(func.get("name", ""))
            if name:
                agent_names.add(name)

    denylist: set[str] = set(api_cfg.tool_invoke_denylist)
    allowlist: set[str] = set(api_cfg.tool_invoke_allowlist)
    expose = api_cfg.tool_invoke_expose

    def _get_name(schema: dict[str, Any]) -> str:
        func = schema.get("function", {})
        return str(func.get("name", ""))

    # 1. 先排除黑名单
    if denylist:
        all_schemas = [s for s in all_schemas if _get_name(s) not in denylist]

    # 2. 白名单非空时仅保留匹配项
    if allowlist:
        return [s for s in all_schemas if _get_name(s) in allowlist]

    # 3. 按 expose 过滤
    if expose == "all":
        return all_schemas

    def _is_tool(name: str) -> bool:
        return "." not in name and name not in agent_names

    def _is_toolset(name: str) -> bool:
        return "." in name and not name.startswith("mcp.")

    filtered: list[dict[str, Any]] = []
    for schema in all_schemas:
        name = _get_name(schema)
        if not name:
            continue
        if expose == "tools" and _is_tool(name):
            filtered.append(schema)
        elif expose == "toolsets" and _is_toolset(name):
            filtered.append(schema)
        elif expose == "tools+toolsets" and (_is_tool(name) or _is_toolset(name)):
            filtered.append(schema)
        elif expose == "agents" and name in agent_names:
            filtered.append(schema)

    return filtered


def get_agent_tool_names(ctx: RuntimeAPIContext) -> set[str]:
    ai = ctx.ai
    if ai is None:
        return set()

    agent_reg = getattr(ai, "agent_registry", None)
    if agent_reg is None:
        return set()

    agent_names: set[str] = set()
    for schema in agent_reg.get_agents_schema():
        func = schema.get("function", {})
        name = str(func.get("name", ""))
        if name:
            agent_names.add(name)
    return agent_names


def resolve_tool_invoke_timeout(
    ctx: RuntimeAPIContext, tool_name: str, timeout: int
) -> float | None:
    if tool_name in get_agent_tool_names(ctx):
        return None
    return float(timeout)


# ------------------------------------------------------------------
# Async helpers
# ------------------------------------------------------------------


async def await_tool_invoke_result(
    awaitable: Awaitable[Any],
    *,
    timeout: float | None,
) -> Any:
    if timeout is None or timeout <= 0:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise _ToolInvokeExecutionTimeoutError from exc


# ------------------------------------------------------------------
# Route handlers
# ------------------------------------------------------------------


async def tools_list_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    _ = request
    cfg = ctx.config_getter()
    if not cfg.api.tool_invoke_enabled:
        return _json_error("Tool invoke API is disabled", status=403)

    tools = get_filtered_tools(ctx)
    return web.json_response({"count": len(tools), "tools": tools})


async def tools_invoke_handler(
    ctx: RuntimeAPIContext,
    background_tasks: set[asyncio.Task[Any]],
    request: web.Request,
) -> Response:
    cfg = ctx.config_getter()
    if not cfg.api.tool_invoke_enabled:
        return _json_error("Tool invoke API is disabled", status=403)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON", status=400)

    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object", status=400)

    tool_name = str(body.get("tool_name", "") or "").strip()
    if not tool_name:
        return _json_error("tool_name is required", status=400)

    args = body.get("args")
    if not isinstance(args, dict):
        return _json_error("args must be a JSON object", status=400)

    # 验证工具是否在允许列表中
    filtered_tools = get_filtered_tools(ctx)
    available_names: set[str] = set()
    for schema in filtered_tools:
        func = schema.get("function", {})
        name = str(func.get("name", ""))
        if name:
            available_names.add(name)

    if tool_name not in available_names:
        caller_ip = request.remote or "unknown"
        logger.warning(
            "[ToolInvoke] 请求拒绝: tool=%s reason=not_available caller_ip=%s",
            tool_name,
            caller_ip,
        )
        return _json_error(f"Tool '{tool_name}' is not available", status=404)

    # 解析回调配置
    callback_cfg = body.get("callback")
    use_callback = False
    callback_url = ""
    callback_headers: dict[str, str] = {}
    if isinstance(callback_cfg, dict) and _to_bool(callback_cfg.get("enabled")):
        callback_url = str(callback_cfg.get("url", "") or "").strip()
        if not callback_url:
            return _json_error(
                "callback.url is required when callback is enabled",
                status=400,
            )
        url_error = _validate_callback_url(callback_url)
        if url_error:
            return _json_error(url_error, status=400)
        raw_headers = callback_cfg.get("headers")
        if isinstance(raw_headers, dict):
            callback_headers = {str(k): str(v) for k, v in raw_headers.items()}
        use_callback = True

    request_id = _uuid.uuid4().hex
    caller_ip = request.remote or "unknown"
    logger.info(
        "[ToolInvoke] 收到请求: request_id=%s tool=%s caller_ip=%s",
        request_id,
        tool_name,
        caller_ip,
    )

    if use_callback:
        # 异步执行 + 回调
        task = asyncio.create_task(
            execute_and_callback(
                ctx,
                request_id=request_id,
                tool_name=tool_name,
                args=args,
                body_context=body.get("context"),
                callback_url=callback_url,
                callback_headers=callback_headers,
                timeout=cfg.api.tool_invoke_timeout,
                callback_timeout=cfg.api.tool_invoke_callback_timeout,
            )
        )
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        return web.json_response(
            {
                "ok": True,
                "request_id": request_id,
                "tool_name": tool_name,
                "status": "accepted",
            }
        )

    # 同步执行
    result = await execute_tool_invoke(
        ctx,
        request_id=request_id,
        tool_name=tool_name,
        args=args,
        body_context=body.get("context"),
        timeout=cfg.api.tool_invoke_timeout,
    )
    return web.json_response(result)


# ------------------------------------------------------------------
# Execution core
# ------------------------------------------------------------------


async def execute_tool_invoke(
    ctx: RuntimeAPIContext,
    *,
    request_id: str,
    tool_name: str,
    args: dict[str, Any],
    body_context: Any,
    timeout: int,
) -> dict[str, Any]:
    """执行工具调用并返回结果字典。"""
    ai = ctx.ai
    if ai is None:
        return {
            "ok": False,
            "request_id": request_id,
            "tool_name": tool_name,
            "error": "AI client not ready",
            "duration_ms": 0,
        }

    # 解析请求上下文
    ctx_data: dict[str, Any] = {}
    if isinstance(body_context, dict):
        ctx_data = body_context
    request_type = str(ctx_data.get("request_type", "api") or "api")
    group_id = ctx_data.get("group_id")
    user_id = ctx_data.get("user_id")
    sender_id = ctx_data.get("sender_id")

    args_keys = list(args.keys())
    logger.info(
        "[ToolInvoke] 开始执行: request_id=%s tool=%s args_keys=%s",
        request_id,
        tool_name,
        args_keys,
    )

    start = time.perf_counter()
    effective_timeout = resolve_tool_invoke_timeout(ctx, tool_name, timeout)
    try:
        async with RequestContext(
            request_type=request_type,
            group_id=int(group_id) if group_id is not None else None,
            user_id=int(user_id) if user_id is not None else None,
            sender_id=int(sender_id) if sender_id is not None else None,
        ) as req_ctx:
            # 注入核心服务资源
            if ctx.sender is not None:
                req_ctx.set_resource("sender", ctx.sender)
            if ctx.history_manager is not None:
                req_ctx.set_resource("history_manager", ctx.history_manager)
            runtime_config = getattr(ai, "runtime_config", None)
            if runtime_config is not None:
                req_ctx.set_resource("runtime_config", runtime_config)
            memory_storage = getattr(ai, "memory_storage", None)
            if memory_storage is not None:
                req_ctx.set_resource("memory_storage", memory_storage)
            if ctx.onebot is not None:
                req_ctx.set_resource("onebot_client", ctx.onebot)
            if ctx.scheduler is not None:
                req_ctx.set_resource("scheduler", ctx.scheduler)
            if ctx.cognitive_service is not None:
                req_ctx.set_resource("cognitive_service", ctx.cognitive_service)
            if ctx.meme_service is not None:
                req_ctx.set_resource("meme_service", ctx.meme_service)

            tool_context: dict[str, Any] = {
                "request_type": request_type,
                "request_id": request_id,
            }
            if group_id is not None:
                tool_context["group_id"] = int(group_id)
            if user_id is not None:
                tool_context["user_id"] = int(user_id)
            if sender_id is not None:
                tool_context["sender_id"] = int(sender_id)

            tool_manager = getattr(ai, "tool_manager", None)
            if tool_manager is None:
                raise RuntimeError("ToolManager not available")

            raw_result = await await_tool_invoke_result(
                tool_manager.execute_tool(tool_name, args, tool_context),
                timeout=effective_timeout,
            )

        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        result_str = str(raw_result or "")
        logger.info(
            "[ToolInvoke] 执行完成: request_id=%s tool=%s ok=true "
            "duration_ms=%s result_len=%d",
            request_id,
            tool_name,
            elapsed_ms,
            len(result_str),
        )
        return {
            "ok": True,
            "request_id": request_id,
            "tool_name": tool_name,
            "result": result_str,
            "duration_ms": elapsed_ms,
        }

    except _ToolInvokeExecutionTimeoutError:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.warning(
            "[ToolInvoke] 执行超时: request_id=%s tool=%s timeout=%ds",
            request_id,
            tool_name,
            timeout,
        )
        return {
            "ok": False,
            "request_id": request_id,
            "tool_name": tool_name,
            "error": f"Execution timed out after {timeout}s",
            "duration_ms": elapsed_ms,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception(
            "[ToolInvoke] 执行失败: request_id=%s tool=%s error=%s",
            request_id,
            tool_name,
            exc,
        )
        return {
            "ok": False,
            "request_id": request_id,
            "tool_name": tool_name,
            "error": str(exc),
            "duration_ms": elapsed_ms,
        }


async def execute_and_callback(
    ctx: RuntimeAPIContext,
    *,
    request_id: str,
    tool_name: str,
    args: dict[str, Any],
    body_context: Any,
    callback_url: str,
    callback_headers: dict[str, str],
    timeout: int,
    callback_timeout: int,
) -> None:
    """异步执行工具并发送回调。"""
    result = await execute_tool_invoke(
        ctx,
        request_id=request_id,
        tool_name=tool_name,
        args=args,
        body_context=body_context,
        timeout=timeout,
    )

    payload = {
        "request_id": result["request_id"],
        "tool_name": result["tool_name"],
        "ok": result["ok"],
        "result": result.get("result"),
        "duration_ms": result.get("duration_ms", 0),
        "error": result.get("error"),
    }

    try:
        cb_timeout = ClientTimeout(total=callback_timeout)
        async with ClientSession(timeout=cb_timeout) as session:
            async with session.post(
                callback_url,
                json=payload,
                headers=callback_headers or None,
            ) as resp:
                logger.info(
                    "[ToolInvoke] 回调发送: request_id=%s url=%s status=%d",
                    request_id,
                    _mask_url(callback_url),
                    resp.status,
                )
    except Exception as exc:
        logger.warning(
            "[ToolInvoke] 回调失败: request_id=%s url=%s error=%s",
            request_id,
            _mask_url(callback_url),
            exc,
        )
