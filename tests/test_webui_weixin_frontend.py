"""微信接入 WebUI 的静态交互契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.utils import io as async_io


WEIXIN_JS = Path("src/Undefined/webui/static/js/weixin.js")


async def _read_source() -> str:
    source = await async_io.read_text(WEIXIN_JS)
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
