"""在 iLink 消息派发边界统一仓库投递错误合同。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from weixin_ilink_client import (
    ApiError,
    ConfigurationError,
    HttpError,
    IlinkTransport,
    SessionPausedError,
    TransportError,
    UnsupportedCapabilityError,
    WeixinCredentials,
    WeixinIlinkError,
)
from weixin_ilink_client.constants import STALE_TOKEN_ERROR_CODE


def is_definitive_weixin_delivery_rejection(exc: BaseException) -> bool:
    """只有明确拒绝的消息结构错误才允许降级重发。"""
    if isinstance(exc, SessionPausedError):
        return False
    if isinstance(exc, UnsupportedCapabilityError):
        return True
    if isinstance(exc, ApiError):
        return exc.code != STALE_TOKEN_ERROR_CODE
    if isinstance(exc, HttpError):
        return 400 <= exc.status_code < 500 and exc.status_code not in {408, 425, 429}
    return False


class WeixinDeliveryUncertainError(WeixinIlinkError):
    """消息已开始派发，但无法确认整体投递完成。"""

    delivery_uncertain: bool = True


class UndefinedIlinkTransport(IlinkTransport):
    """仅适配 sendmessage；媒体上传与其他准备错误保留原有语义。"""

    async def send_message(
        self,
        credentials: WeixinCredentials,
        message: Mapping[str, Any],
    ) -> None:
        try:
            await super().send_message(credentials, message)
        except WeixinIlinkError as exc:
            # 确认未发送与允许更换消息结构降级是两个条件：认证/暂停必须
            # 保留原错误，但不能靠移除引用或拆分多项消息解决。
            if isinstance(exc, (ApiError, ConfigurationError)) or (
                is_definitive_weixin_delivery_rejection(exc)
            ):
                raise
            # SDK 统一包装网络错误，但保留 HTTPX 原因。仅连接/连接池阶段
            # 可确定请求尚未发出；读写失败仍可能已被服务端接收。
            if isinstance(exc, TransportError) and isinstance(
                exc.__cause__,
                (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout),
            ):
                raise
            raise WeixinDeliveryUncertainError(
                "微信投递结果未确认，禁止自动重发"
            ) from exc
