from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from Undefined.webui.app import gzip_middleware


@pytest.mark.parametrize(
    ("suffix", "content_type", "charset"),
    [
        (".txt", "text/plain", "utf-8"),
        (".html", "text/html", "utf-8"),
        (".json", "application/json", None),
    ],
)
async def test_gzip_file_download_preserves_content_and_headers(
    tmp_path: Path, suffix: str, content_type: str, charset: str | None
) -> None:
    original = ("聊天附件内容\n" * 100).encode("utf-8")
    path = tmp_path / f"attachment{suffix}"
    path.write_bytes(original)

    async def handler(request: web.Request) -> web.StreamResponse:
        return web.FileResponse(
            path,
            status=202,
            headers={
                "Content-Disposition": 'attachment; filename="report.txt"',
                "Cache-Control": "no-store",
            },
        )

    request = make_mocked_request(
        "GET", "/api/runtime/chat/file?id=abc", headers={"Accept-Encoding": "gzip"}
    )
    response = await gzip_middleware(request, handler)
    assert isinstance(response, web.Response)
    assert isinstance(response.body, bytes)
    assert gzip.decompress(response.body) == original
    assert response.status == 202
    assert response.content_type == content_type
    assert response.charset == charset
    assert response.headers["Content-Encoding"] == "gzip"
    assert (
        response.headers["Content-Disposition"] == 'attachment; filename="report.txt"'
    )
    assert response.headers["Cache-Control"] == "no-store"


async def test_gzip_file_download_without_accept_encoding_is_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.txt"
    path.write_bytes(b"chat attachment\n" * 100)
    original = web.FileResponse(path)

    async def handler(request: web.Request) -> web.StreamResponse:
        return original

    request = make_mocked_request("GET", "/api/runtime/chat/file?id=abc")
    response = await gzip_middleware(request, handler)
    assert response is original
    assert "Content-Encoding" not in response.headers
