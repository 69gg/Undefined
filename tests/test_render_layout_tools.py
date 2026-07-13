from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.skills.toolsets.render.layout import resolve_render_layout
from Undefined.skills.toolsets.render.render_html.handler import execute as render_html
from Undefined.skills.toolsets.render.render_markdown.handler import (
    execute as render_markdown,
)


class _FakeAttachmentRegistry:
    async def register_local_file(
        self,
        scope_key: str,
        local_path: str | Path,
        **kwargs: Any,
    ) -> Any:
        assert scope_key == "private:42"
        assert Path(local_path).is_file()
        assert kwargs["kind"] == "image"
        return SimpleNamespace(uid="pic_long_image")


def _render_context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "attachment_registry": _FakeAttachmentRegistry(),
        "request_type": "private",
        "runtime_config": SimpleNamespace(
            render_long_image_default_width=900,
            render_long_image_default_padding=28,
        ),
        "user_id": 42,
    }
    context.update(overrides)
    return context


def test_resolve_default_layout_rejects_long_only_parameters() -> None:
    options, error = resolve_render_layout(
        {"layout": "default", "width": 900},
        {},
        content_kind="html",
    )

    assert options is None
    assert error == "width 和 padding 仅支持在 layout=long 时使用"


def test_resolve_long_layout_validates_padding_against_width() -> None:
    options, error = resolve_render_layout(
        {"layout": "long", "width": 320, "padding": 160},
        {},
        content_kind="markdown",
    )

    assert options is None
    assert error == "padding 过大，必须满足 2 * padding < width"


@pytest.mark.asyncio
async def test_render_html_long_layout_uses_explicit_final_width(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from Undefined.utils import paths

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _fake_render(
        html_content: str,
        output_path: str,
        **kwargs: Any,
    ) -> None:
        calls.append((html_content, kwargs))
        Path(output_path).write_bytes(b"png")

    monkeypatch.setattr(paths, "RENDER_CACHE_DIR", tmp_path)
    html = """<!DOCTYPE html><html><body><script src="https://example.com/a.js"></script></body></html>"""
    result = await render_html(
        {
            "html_content": html,
            "layout": "long",
            "width": 1080,
            "padding": 0,
        },
        _render_context(render_html_to_image=_fake_render),
    )

    assert result == '<attachment uid="pic_long_image"/>'
    assert calls[0][0] == html
    assert calls[0][1]["viewport_width"] == 1080
    assert calls[0][1]["screenshot_scale"] == "css"
    style = str(calls[0][1]["screenshot_style"])
    assert "margin: 0 !important" in style
    assert "padding: 0px !important" in style
    assert "script" not in style


@pytest.mark.asyncio
async def test_render_markdown_long_layout_uses_configured_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from Undefined.utils import paths

    calls: list[dict[str, Any]] = []
    markdown_seen = ""

    async def _fake_markdown(content: str) -> str:
        nonlocal markdown_seen
        markdown_seen = content
        return '<article class="markdown-body"><h1>Title</h1></article>'

    async def _fake_render(
        _html_content: str,
        output_path: str,
        **kwargs: Any,
    ) -> None:
        calls.append(kwargs)
        Path(output_path).write_bytes(b"png")

    monkeypatch.setattr(paths, "RENDER_CACHE_DIR", tmp_path)
    context = _render_context(
        render_html_to_image=_fake_render,
        render_markdown_to_html=_fake_markdown,
        runtime_config=SimpleNamespace(
            render_long_image_default_width=960,
            render_long_image_default_padding=32,
        ),
    )
    result = await render_markdown(
        {"content": "# Title", "layout": "long"},
        context,
    )

    assert result == '<attachment uid="pic_long_image"/>'
    assert markdown_seen == "# Title"
    assert calls[0]["viewport_width"] == 960
    assert calls[0]["screenshot_scale"] == "css"
    style = str(calls[0]["screenshot_style"])
    assert "max-width: none !important" in style
    assert "padding: 32px !important" in style


@pytest.mark.asyncio
async def test_render_markdown_default_layout_preserves_original_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from Undefined.utils import paths

    calls: list[dict[str, Any]] = []

    async def _fake_markdown(_content: str) -> str:
        return "<html><body>default</body></html>"

    async def _fake_render(
        _html_content: str,
        output_path: str,
        **kwargs: Any,
    ) -> None:
        calls.append(kwargs)
        Path(output_path).write_bytes(b"png")

    monkeypatch.setattr(paths, "RENDER_CACHE_DIR", tmp_path)
    result = await render_markdown(
        {"content": "default"},
        _render_context(
            render_html_to_image=_fake_render,
            render_markdown_to_html=_fake_markdown,
        ),
    )

    assert result == '<attachment uid="pic_long_image"/>'
    assert calls == [{}]


@pytest.mark.parametrize("tool_name", ["render_html", "render_markdown"])
def test_render_tool_schema_exposes_long_layout(tool_name: str) -> None:
    config_path = (
        Path("src/Undefined/skills/toolsets/render") / tool_name / "config.json"
    )
    schema = json.loads(config_path.read_text(encoding="utf-8"))
    properties = schema["function"]["parameters"]["properties"]

    assert properties["layout"]["enum"] == ["default", "long"]
    assert properties["width"]["minimum"] == 320
    assert properties["width"]["maximum"] == 2048
    assert properties["padding"]["minimum"] == 0
    assert properties["padding"]["maximum"] == 160
