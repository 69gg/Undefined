from __future__ import annotations

import base64
from pathlib import Path

import pytest

from Undefined.api.routes.chat import _normalize_webchat_output
from Undefined.attachments import AttachmentRegistry

# 最小合法 PNG
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_SCOPE = "webui:private:42"


def _registry(tmp_path: Path) -> AttachmentRegistry:
    return AttachmentRegistry(
        registry_path=tmp_path / "registry.json",
        cache_dir=tmp_path / "attachments",
    )


@pytest.mark.asyncio
async def test_normalize_webchat_output_registers_base64_image_as_uid(
    tmp_path: Path,
) -> None:
    """命令输出里的 base64 CQ 图片应注册为附件并替换为 <attachment uid/>，

    避免把整段 base64 写入历史 / 喂给后续 LLM（token 爆炸根因）。
    """
    registry = _registry(tmp_path)
    encoded = base64.b64encode(_PNG_BYTES).decode("ascii")
    content = f"📊 最近 7 天的 Token 使用统计：\n\n[CQ:image,file=base64://{encoded}]"

    text, attachments = await _normalize_webchat_output(
        content,
        registry=registry,
        scope_key=_SCOPE,
        resolve_image_url=None,
        get_forward_messages=None,
    )

    # 文本不再包含 base64，改为 UID 占位
    assert "base64://" not in text
    assert encoded not in text
    assert "<attachment uid=" in text
    assert "📊 最近 7 天的 Token 使用统计" in text
    assert len(text) < len(content)

    # 注册出一个图片附件，UID 可在作用域内解析
    assert len(attachments) == 1
    uid = attachments[0]["uid"]
    assert uid.startswith("pic_")
    assert f'<attachment uid="{uid}"/>' in text
    assert registry.resolve(uid, _SCOPE) is not None


@pytest.mark.asyncio
async def test_normalize_webchat_output_plain_text_unchanged(
    tmp_path: Path,
) -> None:
    """纯文本输出原样返回，不产生附件。"""
    registry = _registry(tmp_path)
    text, attachments = await _normalize_webchat_output(
        "Undefined v3.5.1 发布说明",
        registry=registry,
        scope_key=_SCOPE,
        resolve_image_url=None,
        get_forward_messages=None,
    )
    assert text == "Undefined v3.5.1 发布说明"
    assert attachments == []


@pytest.mark.asyncio
async def test_normalize_webchat_output_no_registry_passthrough() -> None:
    """无注册表 / 作用域时原样返回，不抛错。"""
    text, attachments = await _normalize_webchat_output(
        "纯文本",
        registry=None,
        scope_key=None,
        resolve_image_url=None,
        get_forward_messages=None,
    )
    assert text == "纯文本"
    assert attachments == []
