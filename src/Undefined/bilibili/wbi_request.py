"""Bilibili WBI 签名请求通用逻辑。"""

from typing import Any

import httpx

from Undefined.bilibili.wbi import build_signed_params
import logging

logger = logging.getLogger(__name__)


async def request_with_wbi_fallback(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    params: dict[str, Any],
    log_prefix: str,
    signed_endpoint: str | None = None,
) -> dict[str, Any]:
    """通用 WBI 签名 fallback 请求逻辑。

    三阶段重试：
    1. 无签名请求
    2. 使用缓存的 WBI key 签名重试
    3. 刷新 WBI key 后签名重试

    Args:
        client: httpx 客户端
        endpoint: API 端点 URL（无签名版本）
        params: 请求参数
        log_prefix: 日志前缀（如 "[Bilibili]", "[BilibiliSearch]"）
        signed_endpoint: 可选的签名版本端点 URL，如不提供则使用 endpoint

    Returns:
        API 响应的 JSON 数据

    Raises:
        httpx.HTTPError: 网络请求失败
        ValueError: 响应格式异常
    """
    wbi_endpoint = signed_endpoint or endpoint

    resp = await client.get(endpoint, params=params)
    resp.raise_for_status()
    payload = resp.json()

    if not isinstance(payload, dict):
        raise ValueError(f"{log_prefix} 返回格式异常")
    if int(payload.get("code", -1)) == 0:
        return payload

    code = payload.get("code")
    message = str(payload.get("message") or payload.get("msg") or "未知错误")
    logger.warning(
        "%s 首次失败 code=%s message=%s，尝试 WBI 签名重试",
        log_prefix,
        code,
        message,
    )

    try:
        signed_params = await build_signed_params(client, params)
    except Exception as exc:
        logger.warning("%s 生成 WBI 签名失败: %s", log_prefix, exc)
        return payload

    resp_signed = await client.get(wbi_endpoint, params=signed_params)
    resp_signed.raise_for_status()
    payload_signed = resp_signed.json()
    if not isinstance(payload_signed, dict):
        raise ValueError(f"{log_prefix} WBI 返回格式异常")
    if int(payload_signed.get("code", -1)) == 0:
        logger.info("%s WBI 签名重试成功", log_prefix)
        return payload_signed

    try:
        refreshed_params = await build_signed_params(client, params, force_refresh=True)
    except Exception as exc:
        logger.warning("%s 刷新 WBI key 失败: %s", log_prefix, exc)
        return payload_signed

    if refreshed_params == signed_params:
        return payload_signed

    resp_refreshed = await client.get(wbi_endpoint, params=refreshed_params)
    resp_refreshed.raise_for_status()
    payload_refreshed = resp_refreshed.json()
    if not isinstance(payload_refreshed, dict):
        raise ValueError(f"{log_prefix} 刷新后 WBI 返回格式异常")
    if int(payload_refreshed.get("code", -1)) == 0:
        logger.info("%s 刷新 WBI key 后重试成功", log_prefix)

    return payload_refreshed
