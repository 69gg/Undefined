"""配置备份的同秒保存、历史顺序及恢复兼容性回归。"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.webui.routes import _config


class ConfigRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return cast(dict[str, object], self.body)


@pytest.fixture
def backup_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "config.toml"
    backup_dir = tmp_path / "config_backups"
    monkeypatch.setattr(_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(_config, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(_config, "check_auth", lambda _request: True)

    class FrozenDatetime:
        @staticmethod
        def now(_tz: object) -> datetime:
            return datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(_config, "datetime", FrozenDatetime)
    return config_path


def test_same_timestamp_backups_preserve_each_saved_version(
    backup_config: Path,
) -> None:
    names: list[str] = []
    for value in ("first", "second", "third"):
        backup_config.write_text(f'value = "{value}"\n', encoding="utf-8")
        name = _config._backup_config()
        assert name is not None
        names.append(name)
    assert len(set(names)) == 3
    assert [(_config._BACKUP_DIR / name).read_text() for name in names] == [
        'value = "first"\n',
        'value = "second"\n',
        'value = "third"\n',
    ]


def test_backup_limit_keeps_latest_versions(backup_config: Path) -> None:
    names: list[str] = []
    for index in range(_config._MAX_BACKUPS + 2):
        backup_config.write_text(f"version = {index}\n", encoding="utf-8")
        name = _config._backup_config()
        assert name is not None
        names.append(name)
        os.utime(_config._BACKUP_DIR / name, ns=(index + 1, index + 1))
    assert len(list(_config._BACKUP_DIR.glob("config_*.toml"))) == _config._MAX_BACKUPS
    assert not (_config._BACKUP_DIR / names[0]).exists()
    assert not (_config._BACKUP_DIR / names[1]).exists()
    assert (_config._BACKUP_DIR / names[-1]).read_text() == (
        f"version = {_config._MAX_BACKUPS + 1}\n"
    )


async def test_backup_history_and_restore_accept_legacy_and_unique_names(
    backup_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_config.write_text('value = "original"\n', encoding="utf-8")
    unique_name = _config._backup_config()
    assert unique_name is not None
    unique_path = _config._BACKUP_DIR / unique_name
    legacy = _config._BACKUP_DIR / "config_20261006_120000.toml"
    legacy.write_text('value = "legacy"\n', encoding="utf-8")
    os.utime(legacy, ns=(1, 1))
    os.utime(unique_path, ns=(2, 2))
    monkeypatch.setattr(
        _config, "get_config_manager", lambda: SimpleNamespace(reload=lambda: None)
    )
    request = ConfigRequest(body={})
    response = await _config.config_history_handler(cast(web.Request, request))
    body: dict[str, Any] = json.loads(cast(web.Response, response).text or "{}")
    assert [item["name"] for item in body["backups"]] == [unique_name, legacy.name]
    for name, expected in (
        (unique_name, 'value = "original"\n'),
        (legacy.name, 'value = "legacy"\n'),
    ):
        backup_config.write_text('value = "current"\n', encoding="utf-8")
        request = ConfigRequest(body={"name": name})
        response = await _config.config_restore_handler(cast(web.Request, request))
        assert response.status == 200
        assert backup_config.read_text() == expected
    assert len(list(_config._BACKUP_DIR.glob("config_*.toml"))) == 4


def test_failed_backup_removes_partial_file(
    backup_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup_config.write_text("version = 1\n", encoding="utf-8")

    def fail_copy(_source: Path, target: Path) -> None:
        target.write_text("partial", encoding="utf-8")
        raise OSError("backup write failed")

    monkeypatch.setattr(shutil, "copyfile", fail_copy)
    with pytest.raises(OSError, match="backup write failed"):
        _config._backup_config()
    assert list(_config._BACKUP_DIR.glob("config_*.toml")) == []


def test_missing_config_does_not_create_backup(backup_config: Path) -> None:
    assert _config._backup_config() is None
    assert not _config._BACKUP_DIR.exists()
