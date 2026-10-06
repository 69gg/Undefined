from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request

from Undefined.api import RuntimeAPIContext
from Undefined.api.routes.cognitive import cognitive_profile_handler
from Undefined.cognitive.profile_storage import ProfileStorage
from Undefined.skills.toolsets.cognitive.get_profile.handler import execute


@pytest.mark.asyncio
async def test_profile_paths_are_validated_in_file_io_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = ProfileStorage(tmp_path)
    event_loop_thread = threading.get_ident()
    checked_threads: list[int] = []
    original = storage._contained_path

    def check_path(path: Path) -> Path:
        checked_threads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(storage, "_contained_path", check_path)
    await storage.write_profile("user", "10001", "v1")
    await storage.write_profile("user", "10001", "v2")
    assert await storage.read_profile("user", "10001") == "v2"
    revisions = await storage.list_revisions("user", "10001")
    assert await storage.read_revision("user", "10001", revisions[0]) == "v1"
    await storage.restore_revision("user", "10001", revisions[0])
    assert checked_threads
    assert event_loop_thread not in checked_threads


@pytest.mark.asyncio
async def test_profile_read_checks_links_after_dispatching_file_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "profiles"
    users = base / "users"
    users.mkdir(parents=True)
    (users / "10001.md").write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "10001.md").write_text("private", encoding="utf-8")
    storage = ProfileStorage(base)
    original = asyncio.to_thread

    async def dispatch_after_link_change(
        func: Any, /, *args: Any, **kwargs: Any
    ) -> Any:
        users.rename(base / "original-users")
        users.symlink_to(outside, target_is_directory=True)
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", dispatch_after_link_change)
    with pytest.raises(ValueError, match="超出存储目录"):
        await storage.read_profile("user", "10001")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entity_type", "entity_id"),
    [
        ("other", "10001"),
        ("../user", "10001"),
        ("user", ""),
        ("user", "  "),
        ("user", "."),
        ("user", ".."),
        ("user", "../../outside"),
        ("user", "sub/name"),
        ("user", "sub\\name"),
        ("user", "C:outside"),
        ("user", "name\x00"),
    ],
)
async def test_profile_operations_reject_invalid_entities(
    tmp_path: Path, entity_type: str, entity_id: str
) -> None:
    storage = ProfileStorage(tmp_path / "profiles")
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError):
        await storage.read_profile(entity_type, entity_id)
    with pytest.raises(ValueError):
        await storage.write_profile(entity_type, entity_id, "changed")
    with pytest.raises(ValueError):
        await storage.list_revisions(entity_type, entity_id)
    with pytest.raises(ValueError):
        await storage.read_revision(entity_type, entity_id, "revision.md")
    with pytest.raises(ValueError):
        await storage.restore_revision(entity_type, entity_id, "revision.md")
    with pytest.raises(ValueError):
        storage.merge_guard(entity_type, entity_id)
    assert outside.read_text(encoding="utf-8") == "private"
    assert not storage._locks
    assert not storage._merge_locks
    assert not (tmp_path / "profiles").exists()


@pytest.mark.asyncio
async def test_profile_operations_reject_absolute_id(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    storage = ProfileStorage(tmp_path / "profiles")
    entity_id = str(outside.with_suffix(""))
    with pytest.raises(ValueError):
        await storage.read_profile("user", entity_id)
    with pytest.raises(ValueError):
        await storage.write_profile("user", entity_id, "changed")
    assert outside.read_text(encoding="utf-8") == "private"


@pytest.mark.asyncio
@pytest.mark.parametrize("link_kind", ["directory", "file", "history", "revision"])
async def test_profiles_reject_links_outside_storage(
    tmp_path: Path, link_kind: str
) -> None:
    base = tmp_path / "profiles"
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "10001.md"
    secret.write_text("private", encoding="utf-8")
    base.mkdir()
    storage = ProfileStorage(base)
    if link_kind == "directory":
        (base / "users").symlink_to(outside, target_is_directory=True)
    elif link_kind == "file":
        (base / "users").mkdir()
        (base / "users" / "10001.md").symlink_to(secret)
    else:
        history = base / "history" / "user" / "10001"
        history.parent.mkdir(parents=True)
        if link_kind == "history":
            history.symlink_to(outside, target_is_directory=True)
        else:
            history.mkdir()
            (history / "revision.md").symlink_to(secret)

    if link_kind in {"directory", "file"}:
        with pytest.raises(ValueError):
            await storage.read_profile("user", "10001")
        with pytest.raises(ValueError):
            await storage.write_profile("user", "10001", "changed")
    else:
        with pytest.raises(ValueError):
            await storage.read_revision("user", "10001", "revision.md")
        with pytest.raises(ValueError):
            await storage.restore_revision("user", "10001", "revision.md")
        if link_kind == "history":
            with pytest.raises(ValueError):
                await storage.list_revisions("user", "10001")
            with pytest.raises(ValueError):
                await storage.write_profile("user", "10001", "changed")
    assert secret.read_text(encoding="utf-8") == "private"


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ["user", "group"])
async def test_profiles_keep_valid_non_numeric_ids(
    tmp_path: Path, entity_type: str
) -> None:
    storage = ProfileStorage(tmp_path)
    await storage.write_profile(entity_type, "new-0", "v1")
    await storage.write_profile(entity_type, "new-0", "v2")
    revisions = await storage.list_revisions(entity_type, "new-0")
    await storage.restore_revision(entity_type, "new-0", revisions[0])
    assert await storage.read_profile(entity_type, "new-0") == "v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ["user", "invalid"])
async def test_profile_query_reports_invalid_parameters_without_reading_secret(
    tmp_path: Path, entity_type: str
) -> None:
    storage = ProfileStorage(tmp_path / "profiles")
    (tmp_path / "outside.md").write_text("private", encoding="utf-8")
    service = SimpleNamespace(enabled=True, get_profile=storage.read_profile)
    context = RuntimeAPIContext(
        config_getter=lambda: None,
        onebot=None,
        ai=None,
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
        cognitive_service=service,
    )
    args: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": "../../outside",
    }
    request = make_mocked_request("GET", "/profile", match_info=args)
    response = await cognitive_profile_handler(context, request)
    assert response.status == 400
    assert "private" not in json.loads(response.text or "{}").get("error", "")
    result = await execute(args, {"cognitive_service": service})
    assert result.startswith("侧写查询参数无效:")
    assert "private" not in result
