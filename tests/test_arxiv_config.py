from __future__ import annotations

from pathlib import Path

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


def test_arxiv_config_clamps_invalid_values(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "[arxiv]\n"
            "auto_extract_enabled = true\n"
            "max_file_size = -1\n"
            "auto_extract_group_ids = [123456]\n"
            "auto_extract_private_ids = [20003]\n"
            "auto_extract_max_items = 99\n"
            "author_preview_limit = 0\n"
            "summary_preview_chars = -10\n"
        ),
    )

    assert config.arxiv_auto_extract_enabled is True
    assert config.arxiv_max_file_size == 100
    assert config.arxiv_auto_extract_group_ids == [123456]
    assert config.arxiv_auto_extract_private_ids == [20003]
    assert config.arxiv_auto_extract_max_items == 20
    assert config.arxiv_author_preview_limit == 20
    assert config.arxiv_summary_preview_chars == 1000


def test_arxiv_auto_extract_allowlist_follows_global_access_when_empty(
    tmp_path: Path,
) -> None:
    config = _load_config(
        tmp_path,
        (
            "[access]\n"
            'mode = "allowlist"\n'
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [20003]\n\n"
            "[arxiv]\n"
            "auto_extract_enabled = true\n"
        ),
    )

    assert config.is_arxiv_auto_extract_allowed_group(123456) is True
    assert config.is_arxiv_auto_extract_allowed_group(654321) is False
    assert config.is_arxiv_auto_extract_allowed_private(20003) is True
    assert config.is_arxiv_auto_extract_allowed_private(30004) is False


def test_arxiv_auto_extract_allowlist_overrides_global_access_when_non_empty(
    tmp_path: Path,
) -> None:
    config = _load_config(
        tmp_path,
        (
            "[access]\n"
            'mode = "allowlist"\n'
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [20003]\n\n"
            "[arxiv]\n"
            "auto_extract_enabled = true\n"
            "auto_extract_group_ids = [654321]\n"
            "auto_extract_private_ids = [30004]\n"
        ),
    )

    assert config.is_arxiv_auto_extract_allowed_group(123456) is False
    assert config.is_arxiv_auto_extract_allowed_group(654321) is True
    assert config.is_arxiv_auto_extract_allowed_private(20003) is False
    assert config.is_arxiv_auto_extract_allowed_private(30004) is True
