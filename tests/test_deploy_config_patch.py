"""``config.toml`` 最小差异写入测试。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from Undefined.deploy import config_patch

#: 故意写成「已有注释 + 已有用户自定义值 + 嵌套表」的形态，
#: 用来验证 patch 只动目标键且注释不丢。
EXAMPLE = """\
# zh: 主开关。
# en: Master switch.
# zh: 第二行注释。
nagaagent_mode_enabled = false

[onebot]
# zh: NapCat WebSocket地址。
# en: NapCat WebSocket URL.
ws_url = "ws://127.0.0.1:3001"
# zh: 访问令牌。
token = ""

[webui]
# zh: 监听地址。
url = "127.0.0.1"
# zh: 端口。
port = 8787
# zh: 密码。
password = "changeme"

[api]
# zh: 是否启用。
enabled = true
host = "127.0.0.1"
auth_key = "changeme"

[search]
# zh: SearXNG 地址。
searxng_url = ""
"""


@pytest.fixture
def config_dir(tmp_path: Path) -> tuple[Path, Path, Path]:
    """返回 (config_path, example_path, backup_dir)。"""
    example = tmp_path / "config.toml.example"
    example.write_text(EXAMPLE, encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(EXAMPLE, encoding="utf-8")
    return config, example, tmp_path / "deploy" / "backup"


def _plan(config_path: Path, desired: dict[str, object]) -> config_patch.PatchPlan:
    return config_patch.PatchPlan(
        config_path=config_path,
        desired=desired,
        about={"onebot.ws_url": "协议端地址"},
    )


def test_plan_items_report_current_and_about(
    config_dir: tuple[Path, Path, Path],
) -> None:
    config, _, _ = config_dir
    plan = _plan(
        config,
        {"onebot.ws_url": "ws://napcat:3001", "search.searxng_url": ""},
    )
    items = plan.items(config_patch.load_toml(config))

    assert items[0].key == "onebot.ws_url"
    assert items[0].current == "ws://127.0.0.1:3001"
    assert items[0].value == "ws://napcat:3001"
    assert items[0].is_change is True
    assert items[0].is_conflict is True
    assert items[0].about == "协议端地址"
    # 值本来就相同 -> 不算变更、也不算冲突
    assert items[1].is_change is False
    assert items[1].is_conflict is False


def test_plan_treats_missing_key_as_insert(config_dir: tuple[Path, Path, Path]) -> None:
    config, _, _ = config_dir
    plan = _plan(config, {"onebot.file_send_mode": "url"})
    item = plan.items(config_patch.load_toml(config))[0]
    assert item.current is None
    assert item.is_change is True
    # 键原本不存在，不是“覆盖用户值”，因此不算冲突
    assert item.is_conflict is False


def test_describe_mentions_direction(config_dir: tuple[Path, Path, Path]) -> None:
    config, _, _ = config_dir
    plan = _plan(config, {"webui.url": "0.0.0.0", "webui.port": 8787})
    items = plan.items(config_patch.load_toml(config))
    assert "->" in items[0].describe()
    assert "已是最新" in items[1].describe()


def test_apply_writes_only_target_keys_and_keeps_comments(
    config_dir: tuple[Path, Path, Path],
) -> None:
    config, example, backup_dir = config_dir
    plan = _plan(
        config,
        {
            "onebot.ws_url": "ws://napcat:3001",
            "search.searxng_url": "http://searxng:8080",
        },
    )
    outcome = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert outcome.written is True
    assert outcome.changed_keys == ("onebot.ws_url", "search.searxng_url")
    text = config.read_text(encoding="utf-8")
    # 注释仍在
    assert "# zh: NapCat WebSocket地址。" in text
    assert "# zh: SearXNG 地址。" in text
    # 未触碰的键保持不变
    assert 'token = ""' in text
    assert 'password = "changeme"' in text
    assert "port = 8787" in text
    # 目标键已更新
    parsed = tomllib.loads(text)
    assert parsed["onebot"]["ws_url"] == "ws://napcat:3001"
    assert parsed["search"]["searxng_url"] == "http://searxng:8080"


def test_apply_creates_backup_before_overwrite(
    config_dir: tuple[Path, Path, Path],
) -> None:
    config, example, backup_dir = config_dir
    original = config.read_text(encoding="utf-8")
    plan = _plan(config, {"onebot.ws_url": "ws://napcat:3001"})
    outcome = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert outcome.backup_path is not None
    assert outcome.backup_path.parent == backup_dir
    assert outcome.backup_path.name.startswith(config_patch.BACKUP_FILE_PREFIX)
    # 文件名必须跨平台安全（不含冒号）
    assert ":" not in outcome.backup_path.name
    # 备份内容必须是替换前的原文
    assert outcome.backup_path.read_text(encoding="utf-8") == original


def test_apply_is_noop_when_nothing_changes(
    config_dir: tuple[Path, Path, Path],
) -> None:
    config, example, backup_dir = config_dir
    original = config.read_text(encoding="utf-8")
    plan = _plan(config, {"onebot.ws_url": "ws://127.0.0.1:3001", "webui.port": 8787})
    outcome = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert outcome.written is False
    assert outcome.changed_keys == ()
    assert outcome.backup_path is None
    assert config.read_text(encoding="utf-8") == original
    assert not backup_dir.exists()


def test_apply_is_idempotent(config_dir: tuple[Path, Path, Path]) -> None:
    config, example, backup_dir = config_dir
    plan = _plan(config, {"onebot.ws_url": "ws://napcat:3001"})
    first = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)
    second = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert first.written is True
    assert second.written is False
    assert len(list(backup_dir.glob("config_*.toml"))) == 1


def test_apply_inserts_missing_section(config_dir: tuple[Path, Path, Path]) -> None:
    config, example, backup_dir = config_dir
    plan = _plan(
        config,
        {
            "lxmusic2api.base_url": "http://lxmusic2api:3000",
            "lxmusic2api.api_key": "k" * 32,
        },
    )
    outcome = config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert outcome.written is True
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["lxmusic2api"]["base_url"] == "http://lxmusic2api:3000"
    assert parsed["lxmusic2api"]["api_key"] == "k" * 32


def test_load_toml_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert config_patch.load_toml(tmp_path / "nope.toml") == {}


def test_load_toml_raises_on_broken_syntax(tmp_path: Path) -> None:
    broken = tmp_path / "config.toml"
    broken.write_text("[onebot\n", encoding="utf-8")
    with pytest.raises(config_patch.ConfigError):
        config_patch.load_toml(broken)


def test_broken_config_is_not_modified(config_dir: tuple[Path, Path, Path]) -> None:
    """解析失败时必须中止，且不留下备份等半成品。"""
    config, example, backup_dir = config_dir
    broken_text = "[onebot\n"
    config.write_text(broken_text, encoding="utf-8")
    plan = _plan(config, {"onebot.ws_url": "ws://napcat:3001"})

    with pytest.raises(config_patch.ConfigError):
        config_patch.apply_plan(plan, example_path=example, backup_dir=backup_dir)

    assert config.read_text(encoding="utf-8") == broken_text
    assert not backup_dir.exists()


def test_ensure_config_file_copies_example(config_dir: tuple[Path, Path, Path]) -> None:
    config, example, _ = config_dir
    config.unlink()
    assert config_patch.ensure_config_file(config, example) is True
    assert config.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")
    # 第二次调用不再覆盖
    assert config_patch.ensure_config_file(config, example) is False


def test_ensure_config_file_without_example_raises(tmp_path: Path) -> None:
    with pytest.raises(config_patch.ConfigError):
        config_patch.ensure_config_file(tmp_path / "config.toml", tmp_path / "missing")


def test_build_comment_map_reads_both_files(
    config_dir: tuple[Path, Path, Path],
) -> None:
    config, example, _ = config_dir
    comments = config_patch.build_comment_map(config, example)
    assert "onebot.ws_url" in comments
    assert comments["onebot.ws_url"]["zh"] == "NapCat WebSocket地址。"


def test_build_comment_map_tolerates_missing_files(tmp_path: Path) -> None:
    comments = config_patch.build_comment_map(tmp_path / "a.toml", tmp_path / "b.toml")
    assert comments == {}


def test_rendered_output_is_valid_toml(config_dir: tuple[Path, Path, Path]) -> None:
    config, example, _ = config_dir
    plan = _plan(config, {"webui.password": "p@ss word", "api.auth_key": "k" * 40})
    current = config_patch.load_toml(config)
    rendered = config_patch.render_patched(
        current,
        {item.key: item.value for item in plan.items(current)},
        config_patch.build_comment_map(config, example),
    )
    parsed = tomllib.loads(rendered)
    assert parsed["webui"]["password"] == "p@ss word"
    assert parsed["api"]["auth_key"] == "k" * 40
