from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

RenderContentKind = Literal["html", "markdown"]
RenderLayoutName = Literal["default", "long"]

MIN_LONG_IMAGE_WIDTH = 320
MAX_LONG_IMAGE_WIDTH = 2048
MAX_LONG_IMAGE_PADDING = 160
DEFAULT_LONG_IMAGE_WIDTH = 900
DEFAULT_LONG_IMAGE_PADDING = 28


@dataclass(frozen=True)
class RenderLayoutOptions:
    """已校验的渲染布局选项。"""

    layout: RenderLayoutName
    viewport_width: int | None = None
    screenshot_scale: Literal["css", "device"] = "device"
    screenshot_style: str | None = None

    def render_kwargs(self) -> dict[str, Any]:
        """仅为长图返回额外参数，保持默认调用完全兼容。"""
        if self.layout == "default":
            return {}
        return {
            "viewport_width": self.viewport_width,
            "screenshot_scale": self.screenshot_scale,
            "screenshot_style": self.screenshot_style,
        }


def _config_int(context: Mapping[str, Any], attribute: str, fallback: int) -> int:
    runtime_config = context.get("runtime_config")
    raw_value = getattr(runtime_config, attribute, fallback)
    if isinstance(raw_value, bool):
        return fallback
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return fallback


def _parse_explicit_int(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
) -> tuple[int | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"{name} 必须是整数"
    if value < minimum or value > maximum:
        return None, f"{name} 必须在 {minimum}..{maximum} 之间"
    return value, None


def _long_layout_style(content_kind: RenderContentKind, padding: int) -> str:
    shared = """
html, body {
  margin: 0 !important;
  width: 100% !important;
  min-width: 0 !important;
  max-width: 100% !important;
  overflow-x: hidden !important;
}
img, video, canvas, svg {
  max-width: 100% !important;
}
"""
    if content_kind == "markdown":
        return (
            shared
            + f"""
body {{
  padding: 0 !important;
}}
.markdown-body {{
  box-sizing: border-box !important;
  width: 100% !important;
  min-width: 0 !important;
  max-width: none !important;
  margin: 0 !important;
  padding: {padding}px !important;
  overflow-wrap: anywhere !important;
}}
.markdown-body pre {{
  max-width: 100% !important;
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
}}
"""
        )
    return (
        shared
        + f"""
body {{
  box-sizing: border-box !important;
  padding: {padding}px !important;
}}
"""
    )


def resolve_render_layout(
    args: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    content_kind: RenderContentKind,
) -> tuple[RenderLayoutOptions | None, str | None]:
    """解析并校验工具的 default/long 布局参数。"""
    layout_raw = str(args.get("layout", "default") or "default").strip().lower()
    if layout_raw not in {"default", "long"}:
        return None, f"layout 无效：{layout_raw}。仅支持 default 或 long"

    has_width = args.get("width") is not None
    has_padding = args.get("padding") is not None
    if layout_raw == "default":
        if has_width or has_padding:
            return None, "width 和 padding 仅支持在 layout=long 时使用"
        return RenderLayoutOptions(layout="default"), None

    if has_width:
        width, error = _parse_explicit_int(
            args.get("width"),
            name="width",
            minimum=MIN_LONG_IMAGE_WIDTH,
            maximum=MAX_LONG_IMAGE_WIDTH,
        )
        if error is not None or width is None:
            return None, error
    else:
        width = _config_int(
            context,
            "render_long_image_default_width",
            DEFAULT_LONG_IMAGE_WIDTH,
        )
        width = min(MAX_LONG_IMAGE_WIDTH, max(MIN_LONG_IMAGE_WIDTH, width))

    if has_padding:
        padding, error = _parse_explicit_int(
            args.get("padding"),
            name="padding",
            minimum=0,
            maximum=MAX_LONG_IMAGE_PADDING,
        )
        if error is not None or padding is None:
            return None, error
    else:
        padding = _config_int(
            context,
            "render_long_image_default_padding",
            DEFAULT_LONG_IMAGE_PADDING,
        )
        padding = min(MAX_LONG_IMAGE_PADDING, max(0, padding))

    if padding * 2 >= width:
        return None, "padding 过大，必须满足 2 * padding < width"

    return (
        RenderLayoutOptions(
            layout="long",
            viewport_width=width,
            screenshot_scale="css",
            screenshot_style=_long_layout_style(content_kind, padding),
        ),
        None,
    )
