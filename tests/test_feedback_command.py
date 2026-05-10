"""意见反馈命令测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.feedback import handler as feedback_handler


class _DummySender:
    def __init__(self) -> None:
        self.group_messages: list[tuple[int, str, bool]] = []
        self.private_messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.group_messages.append((group_id, message, mark_sent))

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
    ) -> None:
        _ = auto_history
        self.private_messages.append((user_id, message, mark_sent))


def _commands_dir() -> Path:
    return Path(__import__("Undefined").__path__[0]) / "skills" / "commands"


def _build_context(
    sender: _DummySender,
    *,
    group_id: int = 10001,
    sender_id: int = 12345678,
    user_id: int | None = None,
    scope: str = "group",
    is_admin: bool = False,
    is_superadmin: bool = False,
) -> CommandContext:
    config = cast(
        Any,
        SimpleNamespace(
            is_admin=lambda _sid: is_admin,
            is_superadmin=lambda _sid: is_superadmin,
        ),
    )
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=config,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=cast(Any, SimpleNamespace()),
        scope=scope,
        user_id=user_id,
    )


def _make_record(**overrides: object) -> feedback_handler.FeedbackRecord:
    record: feedback_handler.FeedbackRecord = {
        "id": "20260509-1",
        "content": "希望增加夜间静默模式",
        "scope": "group",
        "group_id": 87654321,
        "user_id": None,
        "sender_id": 12345678,
        "created_at": "2026-05-09T12:00:00+00:00",
    }
    record.update(cast(feedback_handler.FeedbackRecord, overrides))
    return record


@pytest.fixture()
def feedback_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "feedback" / "feedback.json"
    monkeypatch.setattr(feedback_handler, "FEEDBACK_FILE", path)
    monkeypatch.setattr(
        feedback_handler,
        "_now",
        lambda: datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
    )
    return path


def _load_feedback_meta() -> Any:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    return registry.resolve("feedback")


def test_feedback_command_is_registered() -> None:
    dispatcher = CommandDispatcher(
        config=cast(
            Any,
            SimpleNamespace(is_superadmin=lambda _x: False, is_admin=lambda _x: False),
        ),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("feedback")
    assert meta is not None
    assert meta.allow_in_private is True
    assert "fb" in meta.aliases
    assert meta.subcommands["add"].permission == "public"
    assert meta.subcommands["view"].permission == "public"
    assert meta.subcommands["del"].permission == "superadmin"


def test_feedback_alias_fb_resolves() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()

    meta = registry.resolve("fb")
    assert meta is not None
    assert meta.name == "feedback"


def test_feedback_infer_no_args_default_view() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = _load_feedback_meta()
    assert meta is not None

    subcmd, args, submeta = registry.resolve_subcommand(meta, [])

    assert subcmd == "view"
    assert args == ["view"]
    assert submeta is not None


def test_feedback_infer_id_pattern_view() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = _load_feedback_meta()
    assert meta is not None

    subcmd, args, submeta = registry.resolve_subcommand(meta, ["20260509-1000"])

    assert subcmd == "view"
    assert args == ["view", "20260509-1000"]
    assert submeta is not None


def test_feedback_infer_plain_text_fallback_add() -> None:
    registry = CommandRegistry(_commands_dir())
    registry.load_commands()
    meta = _load_feedback_meta()
    assert meta is not None

    subcmd, args, submeta = registry.resolve_subcommand(meta, ["希望", "增加功能"])

    assert subcmd == "add"
    assert args == ["add", "希望", "增加功能"]
    assert submeta is not None


@pytest.mark.asyncio
async def test_feedback_add_group_writes_record(feedback_file: Path) -> None:
    sender = _DummySender()
    context = _build_context(sender, group_id=87654321, sender_id=12345678)

    await feedback_handler.execute(["add", "希望", "增加", "夜间静默模式"], context)

    records = await feedback_handler._load_records()
    assert feedback_file.exists()
    assert len(records) == 1
    assert records[0]["id"] == "20260509-1"
    assert records[0]["content"] == "希望 增加 夜间静默模式"
    assert records[0]["scope"] == "group"
    assert records[0]["group_id"] == 87654321
    assert records[0]["user_id"] is None
    assert records[0]["sender_id"] == 12345678
    assert "已收到反馈：20260509-1" in sender.group_messages[-1][1]


@pytest.mark.asyncio
async def test_feedback_add_private_writes_record(feedback_file: Path) -> None:
    sender = _DummySender()
    context = _build_context(
        sender,
        group_id=0,
        sender_id=22334455,
        user_id=22334455,
        scope="private",
    )

    await feedback_handler.execute(["add", "私聊反馈"], context)

    records = await feedback_handler._load_records()
    assert feedback_file.exists()
    assert len(records) == 1
    assert records[0]["scope"] == "private"
    assert records[0]["group_id"] is None
    assert records[0]["user_id"] == 22334455
    assert records[0]["sender_id"] == 22334455
    assert sender.private_messages[-1][0] == 22334455
    assert "已收到反馈：20260509-1" in sender.private_messages[-1][1]


@pytest.mark.asyncio
async def test_feedback_view_public_does_not_leak_metadata(
    feedback_file: Path,
) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=False)
    await feedback_handler._save_records([_make_record()])

    await feedback_handler.execute(["view", "20260509-1"], context)

    output = sender.group_messages[-1][1]
    assert "希望增加夜间静默模式" in output
    assert "12345678" not in output
    assert "87654321" not in output
    assert "2026-05-09T12:00:00+00:00" not in output
    assert "提交者 QQ" not in output


@pytest.mark.asyncio
async def test_feedback_list_public_render_failure_falls_back_without_metadata(
    feedback_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=False)
    await feedback_handler._save_records([_make_record()])

    async def fail_render(
        html_content: str,
        output_path: str,
        *,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
        device_scale_factor: float = 1.0,
    ) -> None:
        _ = (
            html_content,
            output_path,
            viewport_width,
            viewport_height,
            device_scale_factor,
        )
        raise RuntimeError("render unavailable")

    monkeypatch.setattr("Undefined.render.render_html_to_image", fail_render)

    await feedback_handler.execute(["view"], context)

    output = sender.group_messages[-1][1]
    assert "反馈列表" in output
    assert "20260509-1" in output
    assert "希望增加夜间静默模式" in output
    assert "12345678" not in output
    assert "87654321" not in output
    assert "2026-05-09T12:00:00+00:00" not in output


@pytest.mark.asyncio
async def test_feedback_view_superadmin_shows_audit_info(feedback_file: Path) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=True)
    await feedback_handler._save_records([_make_record()])

    await feedback_handler.execute(["view", "20260509-1"], context)

    output = sender.group_messages[-1][1]
    assert "提交者 QQ: 12345678" in output
    assert "群号: 87654321" in output
    assert "时间: 2026-05-09T12:00:00+00:00" in output
    assert "来源: 群聊" in output


@pytest.mark.asyncio
async def test_feedback_delete_requires_superadmin(feedback_file: Path) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=False)
    await feedback_handler._save_records([_make_record()])

    await feedback_handler.execute(["del", "20260509-1"], context)

    output = sender.group_messages[-1][1]
    assert "仅超级管理员" in output
    assert len(await feedback_handler._load_records()) == 1


@pytest.mark.asyncio
async def test_feedback_delete_superadmin_removes_record(feedback_file: Path) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender, is_superadmin=True)
    await feedback_handler._save_records([_make_record()])

    await feedback_handler.execute(["del", "20260509-1"], context)

    output = sender.group_messages[-1][1]
    assert "已删除反馈：20260509-1" in output
    assert await feedback_handler._load_records() == []


@pytest.mark.asyncio
async def test_feedback_id_continues_after_999(feedback_file: Path) -> None:
    _ = feedback_file
    sender = _DummySender()
    context = _build_context(sender)
    await feedback_handler._save_records(
        [
            _make_record(id="20260509-1"),
            _make_record(id="20260509-999"),
        ]
    )

    await feedback_handler.execute(["add", "第1000条"], context)

    records = await feedback_handler._load_records()
    assert records[-1]["id"] == "20260509-1000"
    assert "已收到反馈：20260509-1000" in sender.group_messages[-1][1]
