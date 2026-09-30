from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.config.loader import Config


def _load_config(tmp_path: Path, extra_toml: str) -> Config:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[core]\n"
            "bot_qq = 10001\n"
            "superadmin_qq = 20002\n\n"
            "[onebot]\n"
            'ws_url = "ws://127.0.0.1:3001"\n\n'
            f"{extra_toml}\n"
        ),
        encoding="utf-8",
    )
    return Config.load(config_path=config_path, strict=False)


def test_jm_defaults_disable_feature(tmp_path: Path) -> None:
    config = _load_config(tmp_path, "")

    assert config.jm_auto_extract_enabled is False
    assert config.jm_use_proxy is False
    assert config.jm_auto_extract_group_ids == []
    assert config.jm_auto_extract_private_ids == []
    assert config.jm_auto_extract_max_items == 1
    assert config.jm_max_file_size == 100
    assert config.jm_max_chapters == 0
    assert config.jm_pdf_dpi == 150.0
    assert config.jm_image_quality == 95
    assert config.jm_download_concurrency == 8
    assert config.jm_request_timeout == 20.0
    assert config.jm_image_timeout == 60.0
    assert config.jm_session_dir == ""


def test_jm_config_clamps_invalid_values(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "[jm]\n"
            "auto_extract_enabled = true\n"
            "auto_extract_max_items = 99\n"
            "max_file_size = -5\n"
            "max_chapters = -1\n"
            "pdf_dpi = 0\n"
            "image_quality = 0\n"
            "download_concurrency = 0\n"
            "request_timeout = 0\n"
            "image_timeout = 0\n"
            'session_dir = "/tmp/jmcpy-home"\n'
        ),
    )

    assert config.jm_auto_extract_enabled is True
    assert config.jm_auto_extract_max_items == 5
    assert config.jm_max_file_size == 100
    assert config.jm_max_chapters == 0
    assert config.jm_pdf_dpi == 150.0
    assert config.jm_image_quality == 95
    assert config.jm_download_concurrency == 8
    assert config.jm_request_timeout == 20.0
    assert config.jm_image_timeout == 60.0
    assert config.jm_session_dir == "/tmp/jmcpy-home"


def test_jm_config_keeps_explicit_values(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "[jm]\n"
            "auto_extract_enabled = true\n"
            "use_proxy = true\n"
            "auto_extract_max_items = 3\n"
            "max_file_size = 0\n"
            "max_chapters = 2\n"
            "pdf_dpi = 200.0\n"
            "image_quality = 100\n"
            "download_concurrency = 32\n"
            "request_timeout = 45.0\n"
            "image_timeout = 120.0\n"
        ),
    )

    assert config.jm_use_proxy is True
    assert config.jm_auto_extract_max_items == 3
    assert config.jm_max_file_size == 0
    assert config.jm_max_chapters == 2
    assert config.jm_pdf_dpi == 200.0
    assert config.jm_image_quality == 100
    assert config.jm_download_concurrency == 32
    assert config.jm_request_timeout == 45.0
    assert config.jm_image_timeout == 120.0


def test_jm_auto_extract_allowlist_follows_global_access_when_empty(
    tmp_path: Path,
) -> None:
    config = _load_config(
        tmp_path,
        (
            "[access]\n"
            'mode = "allowlist"\n'
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [20003]\n\n"
            "[jm]\n"
            "auto_extract_enabled = true\n"
        ),
    )

    assert config.is_jm_auto_extract_allowed_group(123456) is True
    assert config.is_jm_auto_extract_allowed_group(654321) is False
    assert config.is_jm_auto_extract_allowed_private(20003) is True
    assert config.is_jm_auto_extract_allowed_private(30004) is False


def test_jm_auto_extract_allowlist_overrides_global_access_when_non_empty(
    tmp_path: Path,
) -> None:
    config = _load_config(
        tmp_path,
        (
            "[access]\n"
            'mode = "allowlist"\n'
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [20003]\n\n"
            "[jm]\n"
            "auto_extract_enabled = true\n"
            "auto_extract_group_ids = [654321]\n"
            "auto_extract_private_ids = [30004]\n"
        ),
    )

    assert config.is_jm_auto_extract_allowed_group(123456) is False
    assert config.is_jm_auto_extract_allowed_group(654321) is True
    assert config.is_jm_auto_extract_allowed_private(20003) is False
    assert config.is_jm_auto_extract_allowed_private(30004) is True


def test_jm_use_proxy_reads_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JM_USE_PROXY", "true")
    config = _load_config(tmp_path, "")

    assert config.jm_use_proxy is True
