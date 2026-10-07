from __future__ import annotations

import nturl2path
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.api.routes.chat import _normalize_webchat_output
from Undefined.attachments.registry import AttachmentRegistry
from Undefined.attachments.segments import register_message_attachments
from Undefined.onebot.file_references import local_file_path
from Undefined.skills.commands.help import handler as help_handler
from Undefined.utils.paths import file_uri_path_text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename", ["ascii.png", "中文 image.png", "percent%20literal.png"]
)
@pytest.mark.parametrize("kind", ["image", "file"])
@pytest.mark.parametrize("uri", [False, True])
async def test_local_attachment_registration_decodes_only_file_uri(
    tmp_path: Path,
    filename: str,
    kind: str,
    uri: bool,
) -> None:
    source = tmp_path / filename
    source.write_bytes(b"isolated image")
    registry = AttachmentRegistry(
        registry_path=tmp_path / "registry.json", cache_dir=tmp_path / "cache"
    )
    representation = source.as_uri() if uri else str(source)
    result = await register_message_attachments(
        registry=registry,
        segments=[{"type": kind, "data": {"file": representation}}],
        scope_key="private:12345",
    )
    assert len(result.attachments) == 1
    record = registry.resolve(result.attachments[0]["uid"], "private:12345")
    assert record is not None
    assert record.display_name == filename
    assert record.source_ref == representation
    assert record.local_path is not None
    assert Path(record.local_path).read_bytes() == source.read_bytes()


@pytest.mark.asyncio
async def test_help_rendered_uri_becomes_runtime_preview_attachment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_dir = tmp_path / "中文工作区 render%cache"
    registry = AttachmentRegistry(
        registry_path=tmp_path / "registry.json", cache_dir=tmp_path / "cache"
    )
    outputs: list[tuple[str, list[dict[str, str]]]] = []

    async def render(html: str, output: str, **kwargs: Any) -> str:
        Path(output).write_bytes(b"isolated PNG")
        return output

    async def capture(user_id: int, message: str) -> None:
        outputs.append(
            await _normalize_webchat_output(
                message,
                registry=registry,
                scope_key="private:12345",
                resolve_image_url=None,
                get_forward_messages=None,
            )
        )

    context = SimpleNamespace(
        scope="private",
        user_id=12345,
        sender_id=12345,
        group_id=0,
        sender=SimpleNamespace(send_private_message=capture),
    )
    monkeypatch.setattr("Undefined.utils.paths.RENDER_CACHE_DIR", render_dir)
    monkeypatch.setattr("Undefined.render.render_html_to_image", render)
    await help_handler._send_rendered_html(cast(Any, context), "<h1>help</h1>", "help")
    assert len(outputs) == 1
    content, attachments = outputs[0]
    assert len(attachments) == 1
    assert content == f'<attachment uid="{attachments[0]["uid"]}"/>'


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("file:///tmp/percent%2520.txt", "/tmp/percent%20.txt"),
        ("file://LOCALHOST/tmp/report%20file.txt", "/tmp/report file.txt"),
        ("file://server/share/report%20file.txt", "//server/share/report file.txt"),
    ],
)
def test_file_uri_authority_and_single_decoding(uri: str, expected: str) -> None:
    assert file_uri_path_text(uri) == expected
    assert local_file_path(uri) == Path(expected)


def test_file_uri_preserves_windows_drive_and_unc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("Undefined.utils.paths.url2pathname", nturl2path.url2pathname)
    assert file_uri_path_text("file:///C:/Users/Test%20User/report.txt") == (
        r"C:\Users\Test User\report.txt"
    )
    assert file_uri_path_text("file://server/share/report%20file.txt") == (
        r"\\server\share\report file.txt"
    )
