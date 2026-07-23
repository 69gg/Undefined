"""Shared HTTP client for the lxmusic2api-backed music toolset."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import quote, urlsplit

import httpx


class MusicRuntimeConfig(Protocol):
    lxmusic2api_base_url: str
    lxmusic2api_api_key: str
    network_request_timeout: float
    attachment_remote_download_max_size_mb: int


class MusicToolError(RuntimeError):
    """Base exception whose message is safe to return from a tool."""


class MusicConfigError(MusicToolError):
    """Raised when the integration is disabled or misconfigured."""


class MusicApiError(MusicToolError):
    """Raised when lxmusic2api rejects or cannot complete a request."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        status_code: int | None = None,
        request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class StreamedPayload:
    content: bytes
    content_type: str


def runtime_config(context: Mapping[str, Any]) -> MusicRuntimeConfig:
    config = context.get("runtime_config")
    if config is None:
        raise MusicConfigError("缺少运行时配置")
    return cast(MusicRuntimeConfig, config)


def _api_base_url(config: MusicRuntimeConfig) -> str:
    base_url = str(config.lxmusic2api_base_url or "").strip().rstrip("/")
    if not base_url:
        raise MusicConfigError("lxmusic2api.base_url 不能为空")

    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise MusicConfigError("lxmusic2api.base_url 格式无效") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        and parsed.netloc.endswith(":")
    ):
        raise MusicConfigError(
            "lxmusic2api.base_url 必须是无凭据、查询参数和片段的 HTTP(S) 地址"
        )
    if parsed.path.rstrip("/").endswith("/v1"):
        raise MusicConfigError("lxmusic2api.base_url 请填写服务根地址，不要包含 /v1")
    return base_url


def _api_key(config: MusicRuntimeConfig) -> str:
    api_key = str(config.lxmusic2api_api_key or "").strip()
    if not api_key:
        raise MusicConfigError("音乐工具未启用，请先配置 lxmusic2api.api_key")
    return api_key


def _api_url(config: MusicRuntimeConfig, path: str) -> str:
    base_url = _api_base_url(config)
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url}/v1{normalized_path}"


def quote_path_segment(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MusicToolError("路径参数不能为空")
    return quote(normalized, safe="")


def _timeout(config: MusicRuntimeConfig) -> httpx.Timeout:
    timeout_seconds = float(config.network_request_timeout)
    if timeout_seconds <= 0:
        timeout_seconds = 480.0
    return httpx.Timeout(timeout_seconds)


@asynccontextmanager
async def _client(
    context: Mapping[str, Any], config: MusicRuntimeConfig
) -> AsyncIterator[httpx.AsyncClient]:
    injected = context.get("lxmusic2api_http_client")
    if isinstance(injected, httpx.AsyncClient):
        yield injected
        return

    async with httpx.AsyncClient(
        timeout=_timeout(config),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        yield client


def _headers(config: MusicRuntimeConfig, *, stream: bool = False) -> dict[str, str]:
    accept = "audio/*, application/octet-stream" if stream else "application/json"
    return {
        "Accept": accept,
        "Authorization": f"Bearer {_api_key(config)}",
    }


def _api_error(response: httpx.Response) -> MusicApiError:
    code = ""
    message = ""
    request_id = ""
    try:
        payload: object = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", "") or "").strip()
            message = str(error.get("message", "") or "").strip()
            request_id = str(error.get("requestId", "") or "").strip()

    detail = message or f"lxmusic2api 返回 HTTP {response.status_code}"
    if code:
        detail = f"{detail}（{code}）"
    if request_id:
        detail = f"{detail}，request_id={request_id}"
    return MusicApiError(
        detail,
        code=code,
        status_code=response.status_code,
        request_id=request_id,
    )


def _response_data(response: httpx.Response) -> object:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise MusicApiError("lxmusic2api 返回了无效的 JSON") from exc
    if not isinstance(payload, dict) or "data" not in payload:
        raise MusicApiError("lxmusic2api 响应缺少 data 字段")
    return payload["data"]


async def request_data(
    context: Mapping[str, Any],
    method: str,
    path: str,
    *,
    params: Mapping[str, str | int] | None = None,
    json_body: Mapping[str, object] | None = None,
) -> object:
    config = runtime_config(context)
    try:
        async with _client(context, config) as client:
            response = await client.request(
                method,
                _api_url(config, path),
                params=params,
                json=json_body,
                headers=_headers(config),
            )
    except httpx.TimeoutException as exc:
        raise MusicApiError("lxmusic2api 请求超时") from exc
    except httpx.RequestError as exc:
        raise MusicApiError("无法连接 lxmusic2api") from exc

    if not response.is_success:
        raise _api_error(response)
    return _response_data(response)


def _content_length(response: httpx.Response) -> int | None:
    raw_value = str(response.headers.get("content-length", "") or "").strip()
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return value if value >= 0 else None


def _normalized_content_type(response: httpx.Response) -> str:
    return (
        str(response.headers.get("content-type", "") or "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )


def _error_from_bytes(response: httpx.Response, content: bytes) -> MusicApiError:
    parsed = httpx.Response(
        response.status_code,
        headers=response.headers,
        content=content,
        request=response.request,
    )
    return _api_error(parsed)


def _validate_audio_content_type(content_type: str) -> None:
    if not content_type:
        return
    if content_type.startswith("audio/"):
        return
    if content_type in {
        "application/octet-stream",
        "application/ogg",
        "binary/octet-stream",
    }:
        return
    raise MusicApiError(f"lxmusic2api 返回了非音频内容：{content_type}")


async def stream_data(
    context: Mapping[str, Any],
    path: str,
    *,
    json_body: Mapping[str, object],
    max_bytes: int,
) -> StreamedPayload:
    if max_bytes <= 0:
        raise MusicConfigError(
            "附件下载已禁用；请将 delivery 设为 url，或提高 attachments.remote_download_max_size_mb"
        )

    config = runtime_config(context)
    try:
        async with _client(context, config) as client:
            async with client.stream(
                "POST",
                _api_url(config, path),
                json=json_body,
                headers=_headers(config, stream=True),
            ) as response:
                if not response.is_success:
                    error_content = bytearray()
                    async for chunk in response.aiter_bytes():
                        remaining = 64 * 1024 - len(error_content)
                        if remaining <= 0:
                            break
                        error_content.extend(chunk[:remaining])
                    raise _error_from_bytes(response, bytes(error_content))

                content_length = _content_length(response)
                if content_length is not None and content_length > max_bytes:
                    raise MusicApiError(
                        f"音频大小超过附件上限（{content_length} > {max_bytes} 字节）"
                    )
                content_type = _normalized_content_type(response)
                _validate_audio_content_type(content_type)

                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise MusicApiError(f"音频流超过附件上限（{max_bytes} 字节）")
                    content.extend(chunk)
    except MusicToolError:
        raise
    except httpx.TimeoutException as exc:
        raise MusicApiError("lxmusic2api 音频请求超时") from exc
    except httpx.RequestError as exc:
        raise MusicApiError("无法连接 lxmusic2api 音频服务") from exc

    return StreamedPayload(content=bytes(content), content_type=content_type)
