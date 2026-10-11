from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.arxiv.downloader import PaperDownloadResult
from Undefined.arxiv.models import PaperInfo
from Undefined.arxiv.sender import send_arxiv_paper
import Undefined.arxiv.sender as arxiv_sender
from Undefined.handlers.auto_extract import AutoExtractMixin
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import AddressBoundSender, MessageSender


@pytest.fixture(autouse=True)
def _clear_inflight() -> None:
    arxiv_sender._INFLIGHT_SENDS.clear()
    arxiv_sender._RECENT_SENDS.clear()


def _paper_info() -> PaperInfo:
    return PaperInfo(
        paper_id="2501.01234",
        title="Diffusion Policy for Robots",
        authors=("Alice", "Bob", "Carol"),
        summary="A concise summary of the paper.",
        published="2025-01-02T03:04:05Z",
        updated="2025-01-03T03:04:05Z",
        primary_category="cs.RO",
        abs_url="https://arxiv.org/abs/2501.01234",
        pdf_url="https://arxiv.org/pdf/2501.01234.pdf",
    )


def _sender() -> Any:
    return SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_group_file=AsyncMock(),
        send_private_file=AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("first_channel", ["qq", "wechat"])
async def test_auto_extract_deduplicates_per_physical_delivery_address(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    overlap: bool,
    first_channel: str,
) -> None:
    started = {"qq": asyncio.Event(), "wechat": asyncio.Event()}
    release = asyncio.Event()
    if not overlap:
        release.set()

    async def qq_send(
        _user_id: int, _message: list[dict[str, Any]], **_: Any
    ) -> dict[str, Any]:
        started["qq"].set()
        await release.wait()
        return {"data": {"message_id": 11}}

    async def wechat_send(*_: Any, **__: Any) -> str:
        started["wechat"].set()
        await release.wait()
        return "wechat-11"

    onebot: Any = SimpleNamespace(send_private_message=AsyncMock(side_effect=qq_send))
    weixin = SimpleNamespace(send_text=AsyncMock(side_effect=wechat_send))
    history: Any = SimpleNamespace(add_private_message=AsyncMock())
    config: Any = SimpleNamespace(
        is_private_allowed=lambda _: True,
        arxiv_auto_extract_max_items=1,
        arxiv_max_file_size=100,
        arxiv_author_preview_limit=20,
        arxiv_summary_preview_chars=1000,
    )
    sender = MessageSender(onebot, history, bot_qq=999, config=config)
    sender.set_weixin_service(weixin)
    senders: dict[str, Any] = {
        "qq": sender,
        "wechat": AddressBoundSender(sender, DeliveryAddress("wechat", 12345678)),
    }
    handler = AutoExtractMixin.__new__(AutoExtractMixin)
    handler.config = config
    handler.sender = sender
    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(return_value=(PaperDownloadResult(None, None, "failed"), tmp_path)),
    )
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", AsyncMock())

    async def extract(channel: str) -> None:
        await handler._handle_arxiv_extract(
            12345678, ["2501.01234"], "private", senders[channel]
        )

    second_channel = "wechat" if first_channel == "qq" else "qq"
    tasks: list[asyncio.Task[None]] = []
    try:
        tasks.append(asyncio.create_task(extract(first_channel)))
        await asyncio.wait_for(started[first_channel].wait(), timeout=1)
        if not overlap:
            await tasks[0]
        tasks.append(asyncio.create_task(extract(second_channel)))
        await asyncio.wait_for(started[second_channel].wait(), timeout=1)
        if overlap:
            # 两端各有自己的在途发送，同路由的追随者仍应复用。
            tasks.extend(asyncio.create_task(extract(channel)) for channel in senders)
            await asyncio.sleep(0)
            assert all(not task.done() for task in tasks)
    finally:
        release.set()
        await asyncio.gather(*tasks)

    await extract("qq")
    await extract("wechat")
    assert onebot.send_private_message.await_count == 1
    assert weixin.send_text.await_count == 1
    assert history.add_private_message.await_count == 2
    assert set(arxiv_sender._RECENT_SENDS) == {
        ("qq", 12345678, "2501.01234"),
        ("wechat", 12345678, "2501.01234"),
    }
    assert not arxiv_sender._INFLIGHT_SENDS


@pytest.mark.asyncio
async def test_bound_sender_other_target_keeps_qq_deduplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    onebot: Any = SimpleNamespace(
        send_private_message=AsyncMock(return_value={"data": {"message_id": 11}})
    )
    history: Any = SimpleNamespace(add_private_message=AsyncMock())
    config: Any = SimpleNamespace(is_private_allowed=lambda _: True)
    sender = MessageSender(
        onebot,
        history,
        bot_qq=999,
        config=config,
    )
    weixin = SimpleNamespace(send_text=AsyncMock())
    sender.set_weixin_service(weixin)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345678))
    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(
            return_value=(PaperDownloadResult(None, None, "failed"), Path("unused"))
        ),
    )
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", AsyncMock())
    options: dict[str, Any] = {
        "paper_id": "2501.01234",
        "target_type": "private",
        "target_id": 87654321,
        "max_file_size": 100,
        "author_preview_limit": 20,
        "summary_preview_chars": 1000,
    }
    await send_arxiv_paper(sender=cast(Any, bound_sender), **options)
    result = await send_arxiv_paper(sender=sender, **options)

    assert "近期已发送过" in result
    onebot.send_private_message.assert_awaited_once()
    weixin.send_text.assert_not_awaited()
    assert set(arxiv_sender._RECENT_SENDS) == {("qq", 87654321, "2501.01234")}


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_owner", [True, False])
async def test_inflight_send_cancellation_settles_waiters(
    monkeypatch: pytest.MonkeyPatch,
    cancel_owner: bool,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _fake_once(**_: object) -> str:
        started.set()
        await release.wait()
        return "sent"

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)
    options: dict[str, Any] = {
        "paper_id": "2501.01234",
        "sender": _sender(),
        "target_type": "group",
        "target_id": 123456,
        "max_file_size": 100,
        "author_preview_limit": 2,
        "summary_preview_chars": 1000,
    }
    owner = asyncio.create_task(send_arxiv_paper(**options))
    await started.wait()
    follower = asyncio.create_task(send_arxiv_paper(**options))
    await asyncio.sleep(0)
    key = ("group", 123456, "2501.01234")
    future = arxiv_sender._INFLIGHT_SENDS[key]
    assert not follower.done()

    cancelled_task = owner if cancel_owner else follower
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task

    if cancel_owner:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(follower, timeout=1)
        assert future.cancelled()
        assert key not in arxiv_sender._RECENT_SENDS
    else:
        assert not future.done()
        assert not owner.done()
        release.set()
        assert await asyncio.wait_for(owner, timeout=1) == "sent"
        assert future.result() == "sent"
        assert key in arxiv_sender._RECENT_SENDS
    assert key not in arxiv_sender._INFLIGHT_SENDS


@pytest.mark.asyncio
async def test_send_arxiv_paper_sends_info_and_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = _sender()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(
            return_value=(
                PaperDownloadResult(pdf_path, pdf_path.stat().st_size, "downloaded"),
                tmp_path,
            )
        ),
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", cleanup_mock)

    result = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=2,
        summary_preview_chars=1000,
    )

    sender.send_group_message.assert_awaited_once()
    sender.send_group_file.assert_awaited_once()
    cleanup_mock.assert_awaited_once_with(tmp_path)
    assert "PDF" in result


@pytest.mark.asyncio
async def test_send_arxiv_paper_skips_pdf_failure_without_extra_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = _sender()

    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(return_value=(PaperDownloadResult(None, None, "failed"), tmp_path)),
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", cleanup_mock)

    result = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )

    sender.send_group_message.assert_awaited_once()
    sender.send_group_file.assert_not_called()
    cleanup_mock.assert_awaited_once_with(tmp_path)
    assert "未附带 PDF" in result


@pytest.mark.asyncio
async def test_send_arxiv_paper_deduplicates_inflight_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _sender()
    started = asyncio.Event()
    release = asyncio.Event()
    called = 0

    async def _fake_once(**_: object) -> str:
        nonlocal called
        called += 1
        started.set()
        await release.wait()
        return "ok"

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)

    first = asyncio.create_task(
        send_arxiv_paper(
            paper_id="2501.01234",
            sender=sender,
            target_type="group",
            target_id=123456,
            max_file_size=100,
            author_preview_limit=20,
            summary_preview_chars=1000,
        )
    )
    await started.wait()
    second = asyncio.create_task(
        send_arxiv_paper(
            paper_id="2501.01234",
            sender=sender,
            target_type="group",
            target_id=123456,
            max_file_size=100,
            author_preview_limit=20,
            summary_preview_chars=1000,
        )
    )

    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == "ok"
    assert second_result == "ok"
    assert called == 1


@pytest.mark.asyncio
async def test_recent_send_blocks_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a successful send, duplicate should be blocked within cooldown."""
    sender = _sender()
    call_count = 0

    async def _fake_once(**_: object) -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)

    # First send should succeed
    result1 = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )
    assert result1 == "ok"
    assert call_count == 1

    # Second send should be blocked by time-based dedup
    result2 = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )
    assert "近期已发送过" in result2
    assert call_count == 1  # Still only 1 call


@pytest.mark.asyncio
async def test_recent_send_expires_after_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After cooldown expires, the same paper can be sent again."""
    sender = _sender()
    call_count = 0
    mock_time = 0.0

    async def _fake_once(**_: object) -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    def _fake_monotonic() -> float:
        return mock_time

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)
    # Patch time.monotonic in the arxiv_sender module
    monkeypatch.setattr(
        arxiv_sender, "time", SimpleNamespace(monotonic=_fake_monotonic)
    )

    # First send at time 0
    result1 = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )
    assert result1 == "ok"
    assert call_count == 1

    # Advance time past cooldown
    mock_time = arxiv_sender._DEDUP_COOLDOWN_SECONDS + 1.0

    # Second send should succeed now
    result2 = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )
    assert result2 == "ok"
    assert call_count == 2  # Second call executed


@pytest.mark.asyncio
async def test_recent_send_capacity_limit() -> None:
    """When _RECENT_SENDS exceeds max size, oldest entries are evicted."""
    # Fill with max_size + 100 entries
    for i in range(arxiv_sender._RECENT_SENDS_MAX_SIZE + 100):
        key = ("group", i, f"paper_{i}")
        arxiv_sender._RECENT_SENDS[key] = float(i)

    # Trigger eviction
    arxiv_sender._evict_oldest_recent_sends()

    # Should have evicted back to max size
    assert len(arxiv_sender._RECENT_SENDS) == arxiv_sender._RECENT_SENDS_MAX_SIZE

    # Oldest 100 should be gone
    for i in range(100):
        key = ("group", i, f"paper_{i}")
        assert key not in arxiv_sender._RECENT_SENDS

    # Newest max_size should remain
    for i in range(100, arxiv_sender._RECENT_SENDS_MAX_SIZE + 100):
        key = ("group", i, f"paper_{i}")
        assert key in arxiv_sender._RECENT_SENDS


@pytest.mark.asyncio
async def test_cleanup_expired_recent_sends() -> None:
    """Test that expired entries are removed while non-expired remain."""
    import time as time_module

    # Get current time
    now = time_module.monotonic()

    # Add expired entries (old timestamps, more than 1 hour ago)
    expired_key1 = ("group", 1, "expired1")
    expired_key2 = ("group", 2, "expired2")
    arxiv_sender._RECENT_SENDS[expired_key1] = (
        now - arxiv_sender._DEDUP_COOLDOWN_SECONDS - 100.0
    )
    arxiv_sender._RECENT_SENDS[expired_key2] = (
        now - arxiv_sender._DEDUP_COOLDOWN_SECONDS - 50.0
    )

    # Add non-expired entries (recent timestamps, within 1 hour)
    recent_key1 = ("group", 3, "recent1")
    recent_key2 = ("group", 4, "recent2")
    arxiv_sender._RECENT_SENDS[recent_key1] = now - 100.0  # 100 seconds ago
    arxiv_sender._RECENT_SENDS[recent_key2] = now - 10.0  # 10 seconds ago

    # Cleanup
    arxiv_sender._cleanup_expired_recent_sends()

    # Expired should be gone
    assert expired_key1 not in arxiv_sender._RECENT_SENDS
    assert expired_key2 not in arxiv_sender._RECENT_SENDS

    # Recent should remain
    assert recent_key1 in arxiv_sender._RECENT_SENDS
    assert recent_key2 in arxiv_sender._RECENT_SENDS


@pytest.mark.asyncio
async def test_failed_send_not_recorded_in_recent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed send should NOT record in _RECENT_SENDS."""
    sender = _sender()

    async def _fake_once(**_: object) -> str:
        raise RuntimeError("Send failed")

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)

    # Attempt send, should fail
    with pytest.raises(RuntimeError, match="Send failed"):
        await send_arxiv_paper(
            paper_id="2501.01234",
            sender=sender,
            target_type="group",
            target_id=123456,
            max_file_size=100,
            author_preview_limit=20,
            summary_preview_chars=1000,
        )

    # Should NOT be recorded in recent sends
    assert len(arxiv_sender._RECENT_SENDS) == 0
