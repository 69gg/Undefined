"""微信接入 WebUI 的静态交互契约。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from Undefined.utils import io as async_io


WEIXIN_JS = Path("src/Undefined/webui/static/js/weixin.js")
WEIXIN_I18N_JS = Path("src/Undefined/webui/static/js/i18n.js")
WEIXIN_CSS = Path("src/Undefined/webui/static/css/components.css")
WEIXIN_HTML = Path("src/Undefined/webui/templates/index.html")


async def _read_source(path: Path = WEIXIN_JS) -> str:
    source = await async_io.read_text(path)
    assert source is not None
    return source


@pytest.mark.asyncio
async def test_weixin_dialog_traps_and_restores_focus() -> None:
    source = await _read_source()
    show_dialog = source.split("function showDialog()", 1)[1].split(
        "function openBindingDialog", 1
    )[0]
    close_dialog = source.split("async function closeDialog", 1)[1].split(
        "function showConfirmation", 1
    )[0]

    assert "weixinState.dialogPreviousFocus = document.activeElement" in show_dialog
    assert "trapFocus(dialog)" in show_dialog
    assert "releaseFocus(dialog)" in close_dialog
    assert "weixinState.dialogPreviousFocus = null" in close_dialog
    assert "previousFocus.focus()" in close_dialog


@pytest.mark.asyncio
async def test_weixin_qr_step_hides_and_reports_loading_state() -> None:
    html, css, source, i18n = await asyncio.gather(
        _read_source(WEIXIN_HTML),
        _read_source(WEIXIN_CSS),
        _read_source(WEIXIN_JS),
        _read_source(WEIXIN_I18N_JS),
    )

    hidden_rule = css.split(".weixin-qr-step[hidden]", 1)[1].split("}", 1)[0]
    assert "display: none" in hidden_rule
    assert "max-height: min(860px, calc(100dvh - 24px))" in css
    assert 'id="weixinQrFrame"' in html
    assert 'data-state="loading"' in html
    assert 'role="status"' in html
    assert 'data-i18n="weixin.qr_loading"' in html
    assert "function setQrFrameState(state)" in source
    assert 'setQrFrameState("loading")' in source
    assert 'setQrFrameState("error")' in source
    assert "await image.decode()" in source
    assert '"weixin.qr_loading"' in i18n
    assert '"weixin.qr_load_failed"' in i18n
