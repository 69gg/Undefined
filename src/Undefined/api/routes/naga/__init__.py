"""Naga integration route handlers."""

# 同时 re-export 渲染 helper，供 send 路由生成 HTML/Markdown 卡片。
from Undefined.render import render_html_to_image, render_markdown_to_html
from Undefined.api.routes.naga.auth import verify_naga_api_key
from Undefined.api.routes.naga.bind import naga_bind_callback_handler
from Undefined.api.routes.naga.send import (
    naga_messages_send_handler,
    naga_messages_send_impl,
)
from Undefined.api.routes.naga.unbind import naga_unbind_handler

__all__ = [
    "render_html_to_image",
    "render_markdown_to_html",
    "verify_naga_api_key",
    "naga_bind_callback_handler",
    "naga_messages_send_handler",
    "naga_messages_send_impl",
    "naga_unbind_handler",
]
