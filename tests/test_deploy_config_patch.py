"""``config.toml`` 最小差异写入测试。"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from Undefined.deploy import config_patch
from Undefined.webui.utils.comment import parse_comment_map

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

    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    # 未触碰的键保持原值（用结构化断言，而不是对文件原文做子串匹配）
    assert parsed["onebot"]["token"] == ""
    assert parsed["webui"]["password"] == "changeme"
    assert parsed["webui"]["port"] == 8787
    # 目标键已更新
    assert parsed["onebot"]["ws_url"] == "ws://napcat:3001"
    assert parsed["search"]["searxng_url"] == "http://searxng:8080"

    assert parsed["webui"]["url"] == "127.0.0.1"

    # 注释必须真的写进了产物：从**写盘后的文件**解析注释映射来验证。
    # 不能再用 build_comment_map(config, example)——那个函数先读 example，而
    # example 里本来就有这些注释，所以哪怕写完一条注释都不剩也能通过
    # （审查指出的虚假安全感）。
    comments = parse_comment_map(config)
    assert comments["onebot.ws_url"], "目标键的注释在写盘后丢失"
    assert comments["search.searxng_url"], "未触碰键的注释在写盘后丢失"
    assert comments["webui.url"], "同文件其它键的注释在写盘后丢失"


def test_render_drops_unrecognised_comment_blocks(tmp_path: Path) -> None:
    """已知渲染语义：不依附键的独立注释块与无 zh/en 前缀的续行会丢。

    这不是期望行为而是现状约束——`apply_plan` 复用的是 WebUI 的 render_toml，
    只保留 parse_comment_map 能识别的块。把语义固定成测试，避免文档与实现再次
    脱节（文档已如实说明会整份重排）。
    """
    example = tmp_path / "config.toml.example"
    example.write_text(
        "# zh: 主开关。\n"
        "# en: Master switch.\n"
        "# 这行没有 zh/en 前缀，属于续行\n"
        "nagaagent_mode_enabled = false\n"
        "\n"
        "# 独立说明块，不依附任何键\n"
        "\n"
        "[onebot]\n"
        'ws_url = "ws://127.0.0.1:3001"\n',
        encoding="utf-8",
    )
    config = tmp_path / "config.toml"
    config.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    plan = config_patch.PatchPlan(config, {"onebot.ws_url": "ws://napcat:3001"})
    config_patch.apply_plan(plan, example_path=example, backup_dir=tmp_path / "b")

    # 值不丢（走解析而不是原文子串）
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["onebot"]["ws_url"] == "ws://napcat:3001"
    assert parsed["nagaagent_mode_enabled"] is False

    comments = parse_comment_map(config)
    # 能识别的 zh/en 注释块保留
    assert comments["nagaagent_mode_enabled"]["zh"] == "主开关。"
    assert comments["nagaagent_mode_enabled"]["en"] == "Master switch."
    # 现状：无 zh/en 前缀的续行不保留
    assert "这行没有" not in comments["nagaagent_mode_enabled"]["zh"]
    # 现状：不依附任何键的独立说明块整体不保留
    assert all("独立说明块" not in str(value) for value in comments.values())


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


# --------------------------------------------------------------------------- #
# 合并写入计划
# --------------------------------------------------------------------------- #


def test_merge_plans_combines_keys(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    first = config_patch.PatchPlan(config, {"onebot.ws_url": "ws://napcat:3001"})
    second = config_patch.PatchPlan(
        config, {"features.nagaagent_mode_enabled": True}, about={"a": "b"}
    )
    merged = config_patch.merge_plans(first, second)
    assert merged.desired == {
        "onebot.ws_url": "ws://napcat:3001",
        "features.nagaagent_mode_enabled": True,
    }
    assert merged.about == {"a": "b"}


def test_merge_plans_later_wins(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    first = config_patch.PatchPlan(config, {"webui.url": "127.0.0.1"})
    second = config_patch.PatchPlan(config, {"webui.url": "0.0.0.0"})
    assert config_patch.merge_plans(first, second).desired["webui.url"] == "0.0.0.0"


def test_merge_plans_rejects_different_targets(tmp_path: Path) -> None:
    first = config_patch.PatchPlan(tmp_path / "a.toml", {"x": 1})
    second = config_patch.PatchPlan(tmp_path / "b.toml", {"y": 2})
    with pytest.raises(ValueError, match="不同文件"):
        config_patch.merge_plans(first, second)


def test_merge_plans_requires_at_least_one_plan() -> None:
    with pytest.raises(ValueError, match="没有可合并"):
        config_patch.merge_plans()


def test_merge_plans_ignores_empty_plans(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    empty = config_patch.PatchPlan(tmp_path / "other.toml", {})
    real = config_patch.PatchPlan(config, {"x": 1})
    assert config_patch.merge_plans(empty, real).config_path == config
