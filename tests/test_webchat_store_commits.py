from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from Undefined.api import webchat_store
from Undefined.utils import io

_OPERATIONS = (
    "create",
    "rename",
    "clear",
    "append",
    "delete",
    "title_pending",
    "title_generated",
    "title_failed",
)


async def _seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> webchat_store.WebChatConversationStore:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        webchat_store, "WEBCHAT_CONVERSATIONS_DIR", tmp_path / "conversations"
    )
    monkeypatch.setattr(
        webchat_store, "WEBCHAT_MIGRATION_MARKER_FILE", tmp_path / "migration.json"
    )
    monkeypatch.setattr(webchat_store, "HISTORY_DIR", tmp_path / "legacy-history")
    store = webchat_store.WebChatConversationStore()
    await store.ensure_ready()
    await store.create_conversation(conversation_id="existing", title="original")
    for role, text in (("user", "question"), ("bot", "answer")):
        await store.append_message(
            "existing",
            role=role,
            text_content=text,
            display_name="system",
            user_name="system",
        )
    if operation in {"title_generated", "title_failed"}:
        assert await store.mark_title_pending("existing")
    return store


async def _mutate(
    store: webchat_store.WebChatConversationStore, operation: str
) -> object:
    basis = webchat_store._title_basis_hash("question", "answer")
    if operation == "create":
        return await store.create_conversation(conversation_id="new", title="created")
    if operation == "rename":
        return await store.rename_conversation("existing", "renamed")
    if operation == "clear":
        return await store.clear_conversation("existing")
    if operation == "append":
        return await store.append_message(
            "existing",
            role="user",
            text_content="new message",
            display_name="system",
            user_name="system",
        )
    if operation == "delete":
        return await store.delete_conversation("existing")
    if operation == "title_pending":
        return await store.mark_title_pending("existing")
    if operation == "title_generated":
        return await store.apply_generated_title(
            "existing", title="generated", basis_hash=basis
        )
    await store.mark_title_failed("existing", basis)
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_failed_conversation_commit_preserves_cache_disk_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store = await _seed(tmp_path, monkeypatch, operation)
    path = tmp_path / "conversations" / "existing.json"
    before_disk = path.read_bytes()
    before_cache = await store.get_conversation("existing")

    async def wait_for_title() -> None:
        await asyncio.Event().wait()

    pending_title = asyncio.create_task(wait_for_title())
    if operation == "delete":
        store.register_title_task("existing", pending_title)
    original_unlink = Path.unlink

    def failed_write(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
        raise OSError("isolated disk unavailable")

    def failed_unlink(target: Path, *args: Any, **kwargs: Any) -> None:
        if target == path:
            raise OSError("isolated disk unavailable")
        original_unlink(target, *args, **kwargs)

    try:
        with pytest.MonkeyPatch.context() as failure:
            if operation == "delete":
                failure.setattr(Path, "unlink", failed_unlink)
            else:
                failure.setattr(io, "write_json_sync", failed_write)
            with pytest.raises(OSError, match="isolated disk unavailable"):
                await _mutate(store, operation)
        assert path.read_bytes() == before_disk
        assert await store.get_conversation("existing") == before_cache
        assert await store.get_conversation("new") is None
        if operation == "delete":
            assert not pending_title.done()
        await _mutate(store, operation)
        target_id = "new" if operation == "create" else "existing"
        cached = await store.get_conversation(target_id)
        disk_path = tmp_path / "conversations" / f"{target_id}.json"
        if operation == "delete":
            assert cached is None and not disk_path.exists()
            await asyncio.sleep(0)
            assert pending_title.cancelled()
        else:
            assert cached == json.loads(disk_path.read_text(encoding="utf-8"))
        restarted = webchat_store.WebChatConversationStore()
        await restarted.ensure_ready()
        assert await restarted.get_conversation(target_id) == cached
        await restarted.stop()
    finally:
        pending_title.cancel()
        await asyncio.gather(pending_title, return_exceptions=True)
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_cancelled_conversation_commit_finishes_before_unlocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    store = await _seed(tmp_path, monkeypatch, operation)
    target_id = "new" if operation == "create" else "existing"
    target_path = tmp_path / "conversations" / f"{target_id}.json"
    started = threading.Event()
    release = threading.Event()
    original_write = io.write_json_sync
    original_unlink = Path.unlink

    def wait_for_release() -> None:
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test disk release timeout")

    def controlled_write(
        file_path: Path | str, data: Any, use_lock: bool = True
    ) -> None:
        if Path(file_path) == target_path:
            wait_for_release()
        original_write(file_path, data, use_lock)

    def controlled_unlink(target: Path, *args: Any, **kwargs: Any) -> None:
        if target == target_path:
            wait_for_release()
        original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(io, "write_json_sync", controlled_write)
    if operation == "delete":
        monkeypatch.setattr(Path, "unlink", controlled_unlink)
    writing = asyncio.create_task(_mutate(store, operation))
    reader: asyncio.Task[dict[str, Any] | None] | None = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        writing.cancel()
        await asyncio.sleep(0)
        writing.cancel()
        reader = asyncio.create_task(store.get_conversation(target_id))
        await asyncio.sleep(0)
        assert not writing.done()
        assert not reader.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await writing
        cached = await asyncio.wait_for(reader, timeout=2)
        if operation == "delete":
            assert cached is None and not target_path.exists()
        else:
            assert cached is not None
            assert cached == json.loads(target_path.read_text(encoding="utf-8"))
    finally:
        release.set()
        await asyncio.gather(writing, return_exceptions=True)
        if reader is not None:
            await asyncio.gather(reader, return_exceptions=True)
        await store.stop()
