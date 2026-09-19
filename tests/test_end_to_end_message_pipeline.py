"""端到端烟测：真实组件串联的消息处理链路。

与其它单测不同，这里不使用 `MessageHandler.__new__` + SimpleNamespace 拼装，
而是走真实构造路径：

    Config（真实解析） → MessageHandler（真实 __init__）
      → MessageSender / CommandDispatcher / 命令注册表 / SecurityService
      → 队列服务 / 消息合并器 / 管线注册表

只替换两处外部 I/O：OneBot 协议端（记录出站动作）与 LLM（不会在命令链路上被调用）。
覆盖目标：一条群聊斜杠命令能完整走完 access → command → sender → OneBot 调用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from Undefined import __version__
from Undefined.config import ConfigBuilder
from Undefined.config.loader import Config
from Undefined.faq import FAQStorage
from Undefined.handlers import MessageHandler

_BASE_MAPPING: dict[str, Any] = {
    "onebot": {"ws_url": "ws://127.0.0.1:3001", "token": ""},
    "core": {
        "bot_qq": 10001,
        "superadmin_qq": 99999,
        "admin_qqs": [20001],
        "process_every_message": False,
        "process_private_message": True,
        "process_poke_message": False,
        "ai_request_max_retries": 0,
        "context_recent_messages_limit": 5,
        "history_max_records": 20,
    },
    "access": {"mode": "off"},
    "models": {
        "chat": {
            "api_url": "https://api.example.com/v1",
            "api_key": "key",
            "model_name": "chat-model",
            "max_tokens": 512,
        },
        "agent": {
            "api_url": "https://api.example.com/v1",
            "api_key": "key",
            "model_name": "agent-model",
            "max_tokens": 512,
        },
        "vision": {
            "api_url": "https://api.example.com/v1",
            "api_key": "key",
            "model_name": "vision-model",
            "max_tokens": 512,
        },
        # 安全模型检查会真的发起 LLM 请求，端到端用例里关闭
        "security": {"enabled": False},
    },
    "message_batcher": {"enabled": False},
    "automations": {"enabled": False},
    "skills": {"hot_reload": False},
}


def _message_text(message: Any) -> str:
    """把出站消息统一成可断言的文本（可能是字符串或消息段数组）。"""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for segment in message:
            if not isinstance(segment, dict):
                parts.append(str(segment))
                continue
            data = segment.get("data") or {}
            parts.append(str(data.get("text", "")))
        return "".join(parts)
    return str(message)


class _FakeOneBot:
    """记录出站动作的协议端替身。"""

    def __init__(self) -> None:
        self.group_messages: list[tuple[int, str]] = []
        self.private_messages: list[tuple[int, str]] = []

    async def send_group_message(
        self, group_id: int, message: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.group_messages.append((group_id, _message_text(message)))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}

    async def send_private_message(
        self, user_id: int, message: Any, **kwargs: Any
    ) -> dict[str, Any]:
        self.private_messages.append((user_id, _message_text(message)))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 2}}

    async def get_group_info(self, group_id: int) -> dict[str, Any] | None:
        return {"group_id": group_id, "group_name": "端到端测试群"}

    async def get_stranger_info(self, user_id: int) -> dict[str, Any] | None:
        return {"user_id": user_id, "nickname": f"用户{user_id}"}

    async def get_group_member_info(
        self, group_id: int, user_id: int, **kwargs: Any
    ) -> dict[str, Any] | None:
        return {"group_id": group_id, "user_id": user_id, "card": f"群名片{user_id}"}

    async def get_msg(self, message_id: int) -> dict[str, Any] | None:
        return None

    async def get_forward_msg(self, forward_id: str) -> list[dict[str, Any]]:
        return []

    def set_message_handler(self, handler: Any) -> None:  # pragma: no cover - 兼容
        self._message_handler = handler


@pytest.fixture(autouse=True)
def _isolated_history_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把消息历史写进临时目录，避免污染仓库 data/。"""
    import Undefined.utils.history as history_module

    monkeypatch.setattr(history_module, "HISTORY_DIR", str(tmp_path / "history"))


def _build_handler(tmp_path: Path) -> tuple[MessageHandler, _FakeOneBot]:
    config: Config = (
        ConfigBuilder()
        .with_mapping(_BASE_MAPPING)
        .override(
            archive_path=str(tmp_path / "archive"),
            knowledge_base_dir=str(tmp_path / "knowledge"),
        )
        .build(strict=False)
    )
    onebot = _FakeOneBot()
    http_client = httpx.AsyncClient(trust_env=False)
    ai = AsyncMock()
    ai._http_client = http_client
    ai.attachment_registry = None
    ai._meme_service = None
    ai._cognitive_service = None
    ai.memory_storage = None
    ai.model_pool = None
    ai.set_queue_manager = lambda *args, **kwargs: None
    ai.set_command_registry = lambda *args, **kwargs: None

    handler = MessageHandler(config, cast(Any, onebot), ai, FAQStorage())
    return handler, onebot


def _group_event(
    *,
    group_id: int = 30001,
    sender_id: int = 20001,
    text: str = "/version",
    at_bot: bool = False,
) -> dict[str, Any]:
    """构造一条群聊事件；斜杠命令只在 @bot 时生效，因此命令用例需要 at_bot=True。"""
    message: list[dict[str, Any]] = []
    if at_bot:
        message.append({"type": "at", "data": {"qq": "10001"}})
    message.append({"type": "text", "data": {"text": text}})
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": sender_id,
        "message_id": 100,
        "sender": {
            "user_id": sender_id,
            "card": f"群名片{sender_id}",
            "nickname": f"昵称{sender_id}",
            "role": "owner",
            "title": "",
        },
        "message": message,
    }


@pytest.mark.asyncio
async def test_group_slash_command_round_trip_invokes_onebot(tmp_path: Path) -> None:
    handler, onebot = _build_handler(tmp_path)
    try:
        await handler.handle_message(_group_event(at_bot=True, text="/version"))

        assert onebot.group_messages, "命令回复没有通过 OneBot 发送"
        group_id, reply = onebot.group_messages[-1]
        assert group_id == 30001
        assert f"Undefined v{__version__}" in reply
    finally:
        await handler.close()


@pytest.mark.asyncio
async def test_plain_group_message_records_history_without_reply(
    tmp_path: Path,
) -> None:
    """process_every_message=false 且未 @bot 时不应触发 AI 回复，但仍写历史。"""
    handler, onebot = _build_handler(tmp_path)
    try:
        await handler.handle_message(_group_event(at_bot=True, text="今天天气不错"))

        assert onebot.group_messages == []
        await handler.history_manager._ensure_initialized()
        recent = handler.history_manager.get_recent("30001", "group", 0, 10)
        assert any("今天天气不错" in str(item) for item in recent)
    finally:
        await handler.close()


@pytest.mark.asyncio
async def test_disallowed_group_is_ignored(tmp_path: Path) -> None:
    """访问控制生效时，来自未授权群的消息不进历史、不回复。"""
    handler, onebot = _build_handler(tmp_path)
    handler.config.access_mode = "allowlist"
    handler.config.allowed_group_ids = [40000]
    handler.config._refresh_runtime_sets()
    assert handler.config.is_group_allowed(30001) is False
    try:
        await handler.handle_message(_group_event(at_bot=True, text="今天天气不错"))

        assert onebot.group_messages == []
        await handler.history_manager._ensure_initialized()
        assert handler.history_manager.get_recent("30001", "group", 0, 10) == []
    finally:
        await handler.close()
