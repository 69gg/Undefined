from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import AttachmentRegistry
from Undefined.skills.toolsets.render.render_latex import handler
from Undefined.utils import paths

_PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _build_context(registry: AttachmentRegistry) -> dict[str, Any]:
    return {
        "request_type": "group",
        "group_id": 10001,
        "sender_id": 20002,
        "user_id": 20002,
        "attachment_registry": registry,
    }


def test_strip_document_wrappers_removes_document_env() -> None:
    content = (
        "\\begin{document}\n"
        "\\[\n"
        "\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}\n"
        "\\]\n"
        "\\end{document}"
    )
    assert handler._strip_document_wrappers(content) == (
        "\\[\n\\int_{-\\infty}^{+\\infty} e^{-x^2} dx = \\sqrt{\\pi}\n\\]"
    )


def test_strip_document_wrappers_passthrough_for_plain_formula() -> None:
    content = r"\[ E = mc^2 \]"
    assert handler._strip_document_wrappers(content) == content


@pytest.mark.asyncio
async def test_render_latex_embed_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    content = r"\[ \int_{-\infty}^{+\infty} e^{-x^2} dx = \sqrt{\pi} \]"
    rendered_contents: list[str] = []

    monkeypatch.setattr(paths, "RENDER_CACHE_DIR", tmp_path / "render")

    def _fake_render(filepath: Path, render_content: str) -> None:
        rendered_contents.append(render_content)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(_PNG_HEADER)

    monkeypatch.setattr(handler, "_render_latex_image", _fake_render)

    result = await handler.execute(
        {"content": content, "delivery": "embed"},
        _build_context(registry),
    )

    assert result.startswith('<pic uid="')
    assert rendered_contents == [content]
    record = next(iter(registry._records.values()))
    assert record.source_ref == "render_latex"


@pytest.mark.asyncio
async def test_render_latex_returns_helpful_message_when_tex_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    content = r"\[ a = b \]"

    monkeypatch.setattr(paths, "RENDER_CACHE_DIR", tmp_path / "render")

    def _raise_runtime(_: Path, __: str) -> None:
        raise RuntimeError("latex was not able to process the following string")

    monkeypatch.setattr(handler, "_render_latex_image", _raise_runtime)

    result = await handler.execute(
        {"content": content, "delivery": "embed"},
        _build_context(registry),
    )

    assert "TeX Live" in result or "MiKTeX" in result
