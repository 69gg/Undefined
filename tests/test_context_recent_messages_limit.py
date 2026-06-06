from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.ai.prompts import PromptBuilder
from Undefined.config.loader import Config
from Undefined.context import RequestContext
from Undefined.end_summary_storage import EndSummaryRecord


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_loader_does_not_clamp_context_recent_messages_limit(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[core]
context_recent_messages_limit = 500
""",
    )
    assert cfg.context_recent_messages_limit == 500
    assert cfg.get_context_recent_messages_limit() == 500


def test_loader_get_context_recent_messages_limit_large_value(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[core]
context_recent_messages_limit = 10000
""",
    )
    assert cfg.get_context_recent_messages_limit() == 10000


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return []


@pytest.mark.asyncio
async def test_prompt_builder_passes_unclamped_limit_to_history_callback() -> None:
    class _Runtime:
        def get_context_recent_messages_limit(self) -> int:
            return 750

    builder = PromptBuilder(
        bot_qq=123456,
        memory_storage=None,
        end_summary_storage=_FakeEndSummaryStorage(),  # type: ignore[arg-type]
        runtime_config_getter=lambda: _Runtime(),
    )
    captured: list[int] = []
    messages: list[dict[str, Any]] = []

    async def _fake_recent(
        chat_id: str,
        msg_type: str,
        start: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        _ = (chat_id, msg_type, start)
        captured.append(limit)
        return []

    async with RequestContext(request_type="group", group_id=12345, sender_id=10001):
        await builder._inject_recent_messages(
            messages,
            _fake_recent,
            None,
            "hello",
        )

    assert captured == [750]


@pytest.mark.asyncio
async def test_prompt_builder_filters_webchat_display_only_history() -> None:
    class _Runtime:
        def get_context_recent_messages_limit(self) -> int:
            return 10

    builder = PromptBuilder(
        bot_qq=123456,
        memory_storage=None,
        end_summary_storage=_FakeEndSummaryStorage(),  # type: ignore[arg-type]
        runtime_config_getter=lambda: _Runtime(),
    )
    messages: list[dict[str, Any]] = []

    async def _fake_recent(
        chat_id: str,
        msg_type: str,
        start: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        _ = (chat_id, msg_type, start, limit)
        return [
            {
                "type": "private",
                "display_name": "Bot",
                "user_id": "42",
                "chat_id": "42",
                "chat_name": "QQ用户42",
                "timestamp": "2026-05-30 12:00:00",
                "message": "",
                "webchat": {
                    "display_only": True,
                    "events": [
                        {
                            "seq": 2,
                            "event": "tool_end",
                            "payload": {"result_preview": "secret tool result"},
                        }
                    ],
                },
            },
            {
                "type": "private",
                "display_name": "Bot",
                "user_id": "42",
                "chat_id": "42",
                "chat_name": "QQ用户42",
                "timestamp": "2026-05-30 12:00:01",
                "message": "可见回复",
                "webchat": {
                    "display_only": True,
                    "events": [
                        {
                            "seq": 3,
                            "event": "tool_end",
                            "payload": {"result_preview": "visible metadata"},
                        }
                    ],
                },
            },
        ]

    async with RequestContext(request_type="private", user_id=42, sender_id=10001):
        await builder._inject_recent_messages(
            messages,
            _fake_recent,
            None,
            "hello",
        )

    history_message = next(
        str(msg.get("content", ""))
        for msg in messages
        if "【历史消息存档】" in str(msg.get("content", ""))
    )
    assert "secret tool result" not in history_message
    assert "可见回复" in history_message
    assert "visible metadata" not in history_message
