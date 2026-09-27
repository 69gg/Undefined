"""远程附件的目标地址策略与固定 IP 的流式下载。"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import aiohttp
import httpx
from yarl import URL

from Undefined.skills.http_config import build_httpx_client_kwargs


# 与 HTTPX 默认值一致；手动处理跳转，逐跳执行目标策略。
_MAX_REDIRECTS = 20
_STREAM_CHUNK_SIZE = 64 * 1024
_Origin = tuple[str, str, int | None]


class UnsafeAttachmentURL(ValueError):
    """远程附件指向不被允许的地址。"""


def _parse_url(value: str) -> httpx.URL:
    try:
        if any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError("URL 含空白或控制字符")
        url = httpx.URL(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or "%" in url.host
            or "\\" in value
        ):
            raise ValueError("需要不含凭据的 HTTP(S) URL")
    except (httpx.InvalidURL, ValueError) as exc:
        raise UnsafeAttachmentURL("远程附件 URL 格式不受支持") from exc
    return url


def _origin(url: httpx.URL) -> _Origin:
    return url.scheme, url.raw_host.decode("ascii").rstrip("."), url.port


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_site_local:
            return False
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


async def resolve_host_addresses(host: str, port: int) -> tuple[str, ...]:
    """异步解析全部 A/AAAA 结果；连接时使用返回的 IP，避免再次解析域名。"""
    results = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return tuple(dict.fromkeys(str(result[4][0]) for result in results))


@dataclass(frozen=True)
class RemoteURLPolicy:
    """只允许公网目标；受信任内网服务按精确 origin 显式放行。"""

    allowed_origins: frozenset[_Origin] = frozenset()
    max_url_length: int = 8192

    @classmethod
    def create(cls, origins: Iterable[str], max_url_length: int) -> RemoteURLPolicy:
        allowed: set[_Origin] = set()
        for value in origins:
            url = _parse_url(value)
            if url.path != "/" or url.query or url.fragment or "*" in url.host:
                raise ValueError(
                    "附件内网例外必须是精确的 HTTP(S) origin，不支持路径或通配符"
                )
            allowed.add(_origin(url))
        return cls(frozenset(allowed), max_url_length)

    def validate(self, value: str) -> httpx.URL:
        if self.max_url_length > 0 and len(value) > self.max_url_length:
            raise UnsafeAttachmentURL("远程附件 URL 超过长度上限")
        url = _parse_url(value)
        try:
            address = ipaddress.ip_address(url.host)
        except ValueError:
            return url
        if _origin(url) not in self.allowed_origins and not _is_public(str(address)):
            raise UnsafeAttachmentURL("远程附件不允许访问非公网地址")
        return url

    async def resolve(self, value: str) -> tuple[httpx.URL, tuple[str, ...]]:
        url = self.validate(value)
        addresses: tuple[str, ...]
        try:
            addresses = (str(ipaddress.ip_address(url.host)),)
        except ValueError:
            addresses = await resolve_host_addresses(
                url.raw_host.decode("ascii"),
                url.port or (443 if url.scheme == "https" else 80),
            )
        if not addresses or (
            _origin(url) not in self.allowed_origins
            and any(not _is_public(address) for address in addresses)
        ):
            raise UnsafeAttachmentURL("远程附件域名解析到非公网地址或没有可用地址")
        return url, addresses


class _ProxyResponseStream(httpx.AsyncByteStream):
    def __init__(self, response: aiohttp.ClientResponse) -> None:
        self._response = response

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._response.content.iter_chunked(_STREAM_CHUNK_SIZE):
            yield chunk


@asynccontextmanager
async def _open_pinned_response(
    url: httpx.URL,
    addresses: tuple[str, ...],
    *,
    timeout: httpx.Timeout,
    client: httpx.AsyncClient | None,
    proxy_config: Any | None,
) -> AsyncIterator[httpx.Response]:
    kwargs = (
        build_httpx_client_kwargs(
            str(url),
            proxy_scope="attachments",
            timeout=timeout,
            follow_redirects=False,
            config=proxy_config,
        )
        if client is None
        else {}
    )
    proxy = str(kwargs.get("proxy") or "")
    for index, address in enumerate(addresses):
        request = httpx.Request(
            "GET",
            url.copy_with(host=address),
            headers={
                "Host": url.netloc.decode("ascii"),
                "Connection": "close",
                "Accept-Encoding": "identity",
            },
            extensions={
                "sni_hostname": url.raw_host.decode("ascii"),
                "timeout": timeout.as_dict(),
            },
        )
        async with AsyncExitStack() as stack:
            try:
                if client is None and proxy.startswith(("http://", "https://")):
                    # HTTPX/httpcore 的 HTTP CONNECT 路径不支持 sni_hostname。
                    # aiohttp 可分别指定代理连接目标 IP 与目标证书/SNI 主机名。
                    session = await stack.enter_async_context(
                        aiohttp.ClientSession(
                            cookie_jar=aiohttp.DummyCookieJar(),
                            trust_env=False,
                            auto_decompress=False,
                        )
                    )
                    raw = await stack.enter_async_context(
                        session.get(
                            URL(str(request.url), encoded=True),
                            proxy=proxy,
                            headers=dict(request.headers),
                            allow_redirects=False,
                            server_hostname=url.raw_host.decode("ascii"),
                            timeout=aiohttp.ClientTimeout(
                                total=None,
                                sock_connect=timeout.connect,
                                sock_read=timeout.read,
                            ),
                        )
                    )
                    response = httpx.Response(
                        raw.status,
                        headers=raw.raw_headers,
                        stream=_ProxyResponseStream(raw),
                        request=request,
                    )
                else:
                    if client is not None:
                        active_client = client
                    else:
                        active_client = await stack.enter_async_context(
                            httpx.AsyncClient(**kwargs)
                        )
                    response = await active_client.send(
                        request, stream=True, auth=None, follow_redirects=False
                    )
                stack.push_async_callback(response.aclose)
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                aiohttp.ClientConnectorError,
            ):
                if index == len(addresses) - 1:
                    raise
                continue
            yield response
            return


@asynccontextmanager
async def stream_remote_url(
    value: str,
    *,
    policy: RemoteURLPolicy,
    timeout: httpx.Timeout,
    client: httpx.AsyncClient | None = None,
    proxy_config: Any | None = None,
) -> AsyncIterator[httpx.Response]:
    current = value
    for redirects in range(_MAX_REDIRECTS + 1):
        url, addresses = await policy.resolve(current)
        async with _open_pinned_response(
            url, addresses, timeout=timeout, client=client, proxy_config=proxy_config
        ) as response:
            if response.has_redirect_location:
                if redirects == _MAX_REDIRECTS:
                    raise httpx.TooManyRedirects(
                        "远程附件重定向次数超过上限", request=response.request
                    )
                # 相对跳转按原始域名解析，不能按固定 IP 后的 wire URL 解析。
                current = str(url.join(response.headers["location"]))
                continue
            yield response
            return
