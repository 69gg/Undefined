"""``deploy/`` 运行态目录与状态文件测试。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from Undefined.deploy import state
from Undefined.deploy.catalog import COMPOSE_FILE_NAME, ENV_FILE_NAME


def test_layout_paths_are_under_repo(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    assert layout.root == (tmp_path / "deploy").resolve()
    assert layout.state_file.name == "STATE.json"
    assert layout.env_file.name == ENV_FILE_NAME
    assert layout.compose_file.name == COMPOSE_FILE_NAME
    # 各服务目录必须都在 deploy/ 内，避免部署脚本写到仓库别处
    for path in (
        layout.backup_dir,
        layout.data_dir,
        layout.searxng_dir,
        layout.firecrawl_dir,
        layout.lxmusic2api_dir,
        layout.napcat_config_dir,
        layout.napcat_qq_dir,
    ):
        assert layout.root in path.parents


def test_layout_ensure_creates_directories(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    for path in (
        layout.root,
        layout.backup_dir,
        layout.data_dir,
        layout.searxng_dir,
        layout.firecrawl_dir,
        layout.lxmusic2api_private_dir,
        layout.napcat_config_dir,
        layout.napcat_qq_dir,
    ):
        assert path.is_dir()


def test_read_state_returns_none_when_missing(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    assert state.read_state(layout) is None


def test_state_round_trip(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    original = state.DeployState(
        services=("firecrawl", "searxng"),
        mode="container",
        nagaagent=True,
        ports={"bot_webui": 8787, "searxng": 8080},
        image_owner="owner",
    )
    state.save_state(layout, original)

    loaded = state.read_state(layout)
    assert loaded is not None
    assert loaded.services == ("firecrawl", "searxng")
    assert loaded.mode == "container"
    assert loaded.nagaagent is True
    assert loaded.ports == {"bot_webui": 8787, "searxng": 8080}
    assert loaded.image_owner == "owner"
    # generated_at 由 save 补齐，重跑时不应再变
    assert loaded.generated_at


def test_save_state_preserves_generated_at(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    first = state.DeployState(
        services=(), mode="host", generated_at="2026-01-01T00:00:00Z"
    )
    state.save_state(layout, first)
    state.save_state(layout, first)
    loaded = state.read_state(layout)
    assert loaded is not None
    assert loaded.generated_at == "2026-01-01T00:00:00Z"


def test_state_services_are_sorted_in_file(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    state.save_state(
        layout, state.DeployState(services=("searxng", "firecrawl"), mode="host")
    )
    payload = json.loads(layout.state_file.read_text(encoding="utf-8"))
    assert payload["services"] == ["firecrawl", "searxng"]


def test_read_state_ignores_unknown_schema(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    layout.state_file.write_text(
        json.dumps({"schema_version": 999, "mode": "container"}), encoding="utf-8"
    )
    # 版本不认识时按“首次部署”处理，而不是带着错误假设继续
    assert state.read_state(layout) is None


def test_read_state_ignores_broken_json(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    layout.state_file.write_text("{not json", encoding="utf-8")
    assert state.read_state(layout) is None


def test_read_state_tolerates_wrong_field_types(tmp_path: Path) -> None:
    layout = state.DeployLayout.under(tmp_path)
    layout.ensure()
    layout.state_file.write_text(
        json.dumps(
            {
                "schema_version": state.STATE_SCHEMA_VERSION,
                "services": ["searxng", 5],
                "ports": {"searxng": "8080", "bot_webui": 8787},
                "mode": 42,
                "nagaagent": "yes",
            }
        ),
        encoding="utf-8",
    )
    loaded = state.read_state(layout)
    assert loaded is not None
    assert loaded.services == ("searxng",)
    assert loaded.ports == {"bot_webui": 8787}
    assert loaded.mode == ""
    assert loaded.nagaagent is True


def test_write_text_is_atomic_and_leaves_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "out" / "file.txt"
    state.write_text(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    leftovers = [p.name for p in target.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


@pytest.mark.skipif(os.name != "posix", reason="文件权限仅在 POSIX 上有意义")
def test_write_text_secret_uses_0600(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    state.write_text(target, "SECRET=1\n", secret=True)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == state.SECRET_FILE_MODE == 0o600


@pytest.mark.skipif(os.name != "posix", reason="文件权限仅在 POSIX 上有意义")
def test_write_text_non_secret_is_readable(tmp_path: Path) -> None:
    target = tmp_path / "STATE.json"
    state.write_text(target, "{}\n")
    mode = stat.S_IMODE(target.stat().st_mode)
    # 非敏感文件必须对属主可读写；内容正确即说明写成功
    assert mode & stat.S_IRUSR
    assert mode & stat.S_IWUSR


def test_repo_root_contains_pyproject() -> None:
    root = state.repo_root()
    assert (root / "pyproject.toml").is_file()
