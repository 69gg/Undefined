from __future__ import annotations

import asyncio
import shutil
import ssl
import subprocess
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import httpx
import pytest

from Undefined.attachments import AttachmentRegistry, register_message_attachments
from Undefined.attachments import remote
from Undefined.attachments.remote import RemoteURLPolicy, UnsafeAttachmentURL


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, ...]]:
    records: dict[str, tuple[str, ...]] = {
        "public.test": ("93.184.216.34",),
        "other.test": ("93.184.216.35",),
        "internal.test": ("10.0.0.1",),
        "127.1": ("127.0.0.1",),
        "2130706433": ("127.0.0.1",),
        "0x7f000001": ("127.0.0.1",),
    }

    async def resolve(host: str, port: int) -> tuple[str, ...]:
        return records[host]

    monkeypatch.setattr(remote, "resolve_host_addresses", resolve)
    return records


def _registry(
    tmp_path: Path, client: httpx.AsyncClient, **kwargs: Any
) -> AttachmentRegistry:
    return AttachmentRegistry(
        registry_path=tmp_path / "registry.json",
        cache_dir=tmp_path / "cache",
        http_client=client,
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[::]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[fec0::1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://internal.test/",
    ],
)
async def test_non_public_destinations_never_reach_transport(
    tmp_path: Path, dns: dict[str, tuple[str, ...]], url: str
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"blocked destination reached transport: {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        registry = _registry(tmp_path, client)
        with pytest.raises(UnsafeAttachmentURL):
            await registry.register_remote_url("group:1", url, kind="image")
    assert registry._records == {}


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://public.test/file",
        "//public.test/file",
        "http://user:pass@public.test/",
        "http://[fe80::1%25eth0]/",
        "http://public.test\\@internal.test/",
        "http://public.test/\nfile",
    ],
)
def test_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(UnsafeAttachmentURL):
        RemoteURLPolicy().validate(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [(), ("93.184.216.34", "10.0.0.1")])
async def test_empty_or_mixed_dns_answer_is_rejected(
    dns: dict[str, tuple[str, ...]], addresses: tuple[str, ...]
) -> None:
    dns["public.test"] = addresses
    with pytest.raises(UnsafeAttachmentURL):
        await RemoteURLPolicy().resolve("https://public.test/image")


@pytest.mark.asyncio
async def test_download_pins_resolved_ip_and_preserves_host_sni_and_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolutions = 0

    async def resolve(host: str, port: int) -> tuple[str, ...]:
        nonlocal resolutions
        resolutions += 1
        assert (host, port) == ("public.test", 8443)
        return ("93.184.216.34",) if resolutions == 1 else ("127.0.0.1",)

    monkeypatch.setattr(remote, "resolve_host_addresses", resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.url.query == b"token=a%2Fb"
        assert request.headers["host"] == "public.test:8443"
        assert request.extensions["sni_hostname"] == "public.test"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"image")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=("secret", "secret")
    ) as client:
        record = await _registry(tmp_path, client).register_remote_url(
            "group:1", "https://public.test:8443/image?token=a%2Fb", kind="image"
        )
    assert resolutions == 1
    assert record.source_ref == "https://public.test:8443/image?token=a%2Fb"
    assert Path(str(record.local_path)).read_bytes() == b"image"


@pytest.mark.asyncio
async def test_redirect_targets_are_checked_even_if_client_follows_redirects(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://internal.test/secret"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        registry = _registry(tmp_path, client)
        with pytest.raises(UnsafeAttachmentURL):
            await registry.register_remote_url(
                "group:1", "https://public.test/start", kind="image"
            )
    assert requested == ["https://93.184.216.34/start"]
    assert registry._records == {}


@pytest.mark.asyncio
async def test_relative_redirect_keeps_logical_host_and_closes_responses(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["host"] == "public.test"
        assert request.url.host == "93.184.216.34"
        response = (
            httpx.Response(302, headers={"location": "../final?token=a%2Fb"})
            if request.url.path == "/a/start"
            else httpx.Response(200, content=b"ok")
        )
        responses.append(response)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        record = await _registry(tmp_path, client).register_remote_url(
            "group:1", "https://public.test/a/start", kind="image"
        )
    assert len(responses) == 2
    assert all(response.is_closed for response in responses)
    assert Path(str(record.local_path)).read_bytes() == b"ok"


@pytest.mark.asyncio
async def test_dns_is_rechecked_on_same_host_redirect(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        dns["public.test"] = ("127.0.0.1",)
        return httpx.Response(302, headers={"location": "/next"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeAttachmentURL):
            await _registry(tmp_path, client).register_remote_url(
                "group:1", "https://public.test/start", kind="image"
            )


@pytest.mark.asyncio
async def test_private_origin_exception_is_exact_and_revoked_on_reload(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert request.url.host == "10.0.0.1"
        return httpx.Response(200, headers={"content-length": "1024"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        registry = _registry(
            tmp_path,
            client,
            remote_download_max_bytes=1,
            remote_download_allow_private_origins=["http://internal.test:8080"],
        )
        reference = await registry.register_remote_url(
            "group:1", "http://internal.test:8080/file", kind="file"
        )
        assert reference.local_path is None
        for url in (
            "https://internal.test:8080/file",
            "http://internal.test:8081/file",
        ):
            with pytest.raises(UnsafeAttachmentURL):
                await registry.register_remote_url("group:1", url, kind="file")
        registry.set_limits(remote_download_allow_private_origins=[])
        with pytest.raises(UnsafeAttachmentURL):
            await registry.ensure_local_file(reference)
    assert requests == 1


@pytest.mark.asyncio
async def test_reference_refetch_resolves_again_before_fetching(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("refetch to private destination reached transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        registry = _registry(tmp_path, client, remote_download_max_bytes=0)
        reference = await registry.register_remote_url(
            "group:1", "https://public.test/file", kind="file"
        )
        registry.set_remote_download_max_bytes(1024)
        dns["public.test"] = ("127.0.0.1",)
        with pytest.raises(UnsafeAttachmentURL):
            await registry.ensure_local_file(reference)


@pytest.mark.asyncio
async def test_image_fallback_obeys_destination_policy(
    tmp_path: Path, dns: dict[str, tuple[str, ...]]
) -> None:
    async def failed_resolver(file_id: str) -> str:
        raise RuntimeError("get_image failed")

    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("unsafe image fallback reached transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        result = await register_message_attachments(
            registry=_registry(tmp_path, client),
            scope_key="group:1",
            segments=[
                {
                    "type": "image",
                    "data": {"file": "id", "url": "http://internal.test/file"},
                }
            ],
            resolve_image_url=failed_resolver,
        )
    assert result.attachments == []


@pytest.mark.asyncio
async def test_dns_resolution_shares_download_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(host: str, port: int) -> tuple[str, ...]:
        await asyncio.Event().wait()
        return ()

    monkeypatch.setattr(remote, "resolve_host_addresses", resolve)
    monkeypatch.setattr(
        "Undefined.attachments.registry._DEFAULT_REMOTE_TIMEOUT_SECONDS", 0.01
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        with pytest.raises(TimeoutError):
            await _registry(tmp_path, client).register_remote_url(
                "group:1", "https://public.test/image", kind="image"
            )


@pytest.mark.parametrize(
    "value", ["http://*.internal", "http://internal/path", "http://internal?token=a"]
)
def test_invalid_private_origin_configuration_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        RemoteURLPolicy.create([value], 8192)


@pytest.fixture
async def tls_origin(
    tmp_path: Path,
) -> AsyncIterator[tuple[int, ssl.SSLContext, list[str | None], list[bytes]]]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL is required for the local TLS integration tests")
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=public.test",
            "-addext",
            "subjectAltName=DNS:public.test",
        ],
        capture_output=True,
        check=True,
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    names: list[str | None] = []
    requests: list[bytes] = []

    def record_sni(
        connection: ssl.SSLObject | ssl.SSLSocket,
        name: str | None,
        context: object,
    ) -> None:
        names.append(name)

    server_context.set_servername_callback(record_sni)

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
    async with server:
        yield (
            int(server.sockets[0].getsockname()[1]),
            ssl.create_default_context(cafile=str(cert)),
            names,
            requests,
        )


@pytest.mark.asyncio
async def test_direct_tls_preserves_original_certificate_hostname(
    tmp_path: Path,
    dns: dict[str, tuple[str, ...]],
    tls_origin: tuple[int, ssl.SSLContext, list[str | None], list[bytes]],
) -> None:
    port, trusted_ca, names, requests = tls_origin
    dns["public.test"] = ("127.0.0.1",)
    url = f"https://public.test:{port}/image"
    async with httpx.AsyncClient(verify=trusted_ca, trust_env=False) as client:
        record = await _registry(
            tmp_path,
            client,
            remote_download_allow_private_origins=[f"https://public.test:{port}"],
        ).register_remote_url("group:1", url, kind="image")
    assert names == ["public.test"]
    assert f"Host: public.test:{port}".encode() in requests[0]
    assert Path(str(record.local_path)).read_bytes() == b"ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["public.test", "other.test"])
async def test_https_proxy_pins_connect_target_and_verifies_original_hostname(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dns: dict[str, tuple[str, ...]],
    host: str,
    tls_origin: tuple[int, ssl.SSLContext, list[str | None], list[bytes]],
) -> None:
    port, trusted_ca, names, requests = tls_origin
    monkeypatch.setattr(aiohttp.connector, "_SSL_CONTEXT_VERIFIED", trusted_ca)
    connect_requests: list[bytes] = []

    async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while chunk := await reader.read(65536):
                writer.write(chunk)
                await writer.drain()
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readuntil(b"\r\n\r\n")
        connect_requests.append(request)
        # 测试代理仅把指定测试目标转发到本地 TLS fixture，不访问真实公网。
        upstream_reader, upstream_writer = await asyncio.open_connection(
            "127.0.0.1", port
        )
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(
            pipe(reader, upstream_writer), pipe(upstream_reader, writer)
        )

    server = await asyncio.start_server(proxy, "127.0.0.1", 0)
    async with server:
        proxy_port = int(server.sockets[0].getsockname()[1])
        registry = AttachmentRegistry(
            registry_path=tmp_path / "registry.json",
            cache_dir=tmp_path / "cache",
            proxy_config=SimpleNamespace(
                attachment_use_proxy=True,
                https_proxy=f"http://127.0.0.1:{proxy_port}",
                http_proxy="",
            ),
        )
        if host == "public.test":
            record = await registry.register_remote_url(
                "group:1", f"https://{host}:{port}/image?token=a%2Fb", kind="image"
            )
            assert Path(str(record.local_path)).read_bytes() == b"ok"
            assert b"/image?token=a%2Fb" in requests[0]
            assert f"host: {host}:{port}".encode() in requests[0].lower()
        else:
            with pytest.raises(aiohttp.ClientConnectorCertificateError):
                await registry.register_remote_url(
                    "group:1", f"https://{host}:{port}/image", kind="image"
                )
            assert registry._records == {}
            assert requests == []
    assert names == [host]
    assert len(connect_requests) == 1
    assert connect_requests[0].startswith(
        f"CONNECT {dns[host][0]}:{port} HTTP/1.1\r\n".encode()
    )
