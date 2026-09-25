"""``uv run deploy`` 的参数解析测试。

这些用例不依赖 Docker，也不触碰磁盘：``cli`` 只做参数归一化。
"""

from __future__ import annotations

import argparse

import pytest

from Undefined.deploy import catalog, cli


def test_defaults_are_all_off() -> None:
    """默认不部署任何可选服务、不拉 NagaAgent——这是最保守的默认行为。"""
    args = cli.build_parser().parse_args(["up"])
    assert args.services is None
    assert cli.normalize_services(args.services) == ()
    assert args.nagaagent is None
    assert args.mode is None
    assert args.dry_run is False


def test_with_accepts_comma_separated_list() -> None:
    args = cli.build_parser().parse_args(["up", "--with", "searxng,lxmusic2api"])
    assert cli.normalize_services(args.services) == ("searxng", "lxmusic2api")


def test_with_accepts_per_service_flags() -> None:
    args = cli.build_parser().parse_args(["up", "--with-searxng", "--with-firecrawl"])
    assert cli.normalize_services(args.services, args.service_flags) == (
        "searxng",
        "firecrawl",
    )


def test_with_merges_list_and_flags() -> None:
    args = cli.build_parser().parse_args(
        ["up", "--with", "searxng", "--with-firecrawl"]
    )
    assert cli.normalize_services(args.services, args.service_flags) == (
        "searxng",
        "firecrawl",
    )


def test_with_deduplicates_and_keeps_order() -> None:
    args = cli.build_parser().parse_args(
        ["up", "--with", "firecrawl,searxng,firecrawl"]
    )
    assert cli.normalize_services(args.services) == ("firecrawl", "searxng")


def test_with_rejects_unknown_service() -> None:
    with pytest.raises(KeyError) as excinfo:
        cli.normalize_services("nope")
    # 报错要列出可选服务，用户不必翻文档
    assert "searxng" in str(excinfo.value)


def test_nagaagent_flags_are_mutually_exclusive() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["up", "--with-nagaagent"]).nagaagent is True
    assert parser.parse_args(["up", "--no-nagaagent"]).nagaagent is False
    with pytest.raises(SystemExit):
        parser.parse_args(["up", "--with-nagaagent", "--no-nagaagent"])


@pytest.mark.parametrize("mode", catalog.DEPLOY_MODES)
def test_mode_accepts_both_deployment_modes(mode: str) -> None:
    args = cli.build_parser().parse_args(["up", "--mode", mode])
    assert args.mode == mode


def test_mode_rejects_unknown_value() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["up", "--mode", "kubernetes"])


def test_parse_ports_accepts_known_keys() -> None:
    assert cli.parse_ports(["bot_webui=10000", "napcat_ws=13001"]) == {
        "bot_webui": 10000,
        "napcat_ws": 13001,
    }


def test_parse_ports_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="未知端口键"):
        cli.parse_ports(["nope=1"])


@pytest.mark.parametrize(
    "raw", ["bot_webui", "bot_webui=abc", "bot_webui=0", "bot_webui=70000"]
)
def test_parse_ports_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        cli.parse_ports([raw])


def test_parse_ports_returns_empty_for_none() -> None:
    assert cli.parse_ports(None) == {}


def test_every_port_key_is_exposed_by_help() -> None:
    """``up --port`` 的 help 必须列全端口键，否则用户无法发现可覆盖项。"""
    help_text = _up_help_text()
    for key in catalog.port_specs():
        assert key in help_text


def test_all_optional_services_are_exposed_by_help() -> None:
    help_text = _up_help_text()
    for service in catalog.OPTIONAL_SERVICES:
        assert service.key in help_text


def _up_help_text() -> str:
    """取 ``up`` 子命令的 help（这些选项都挂在子命令上）。"""
    parser = cli.build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse 无公开子解析器访问器
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            up_parser = action.choices["up"]
            assert isinstance(up_parser, argparse.ArgumentParser)
            return up_parser.format_help()
    raise AssertionError("未找到 up 子命令")


def test_no_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "up" in capsys.readouterr().out
