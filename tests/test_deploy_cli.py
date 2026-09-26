"""``uv run deploy`` 的参数解析测试。

这些用例不依赖 Docker，也不触碰磁盘：``cli`` 只做参数归一化。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from Undefined.deploy import catalog, cli, commands, docker_cli, runner
from Undefined.deploy.state import DeployLayout


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


def test_invalid_service_reports_error_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """用户输入错误必须走项目约定的「错误：...」而不是抛 Python 栈。

    归一化曾在 try 之外，`--with nope` 会打印完整 traceback。
    """
    assert cli.main(["up", "--dry-run", "--with", "nope"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("错误：")
    assert "searxng" in out
    assert "Traceback" not in out


def test_invalid_port_reports_error_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["up", "--dry-run", "--port", "nope=1"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("错误：")
    assert "bot_webui" in out
    assert "Traceback" not in out


def test_non_integer_port_reports_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["up", "--dry-run", "--port", "bot_webui=abc"]) == 1
    assert "必须是整数" in capsys.readouterr().out


def test_no_subcommand_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main([]) == 0
    assert "up" in capsys.readouterr().out


def _capture_up_options(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> dict[str, Any]:
    """跑一次 ``cli.main``，返回它交给 ``dispatch`` 的 up 选项。"""
    captured: list[dict[str, Any]] = []

    def fake_up(options: dict[str, Any]) -> int:
        captured.append(options)
        return 0

    # dispatch 用的是 commands 模块里的名字，必须打在它上面
    monkeypatch.setattr(commands, "run_up", fake_up)
    assert cli.main(argv) == 0
    assert captured, "up 没有被分发"
    return captured[0]


def test_up_without_service_option_dispatches_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没给任何服务选项时必须传 ``None``：那是「未指定」，交给 runner 沿用/提问。

    旧实现无条件归一化，把「没给 --with」变成空元组，而空元组在 runner 里是
    「显式清空」——重跑 up 会把上次选的服务悄悄去掉，``--remove-orphans``
    顺势删掉它们的容器；交互向导里也不再沿用上次的选择。
    """
    options = _capture_up_options(monkeypatch, ["up", "--yes"])
    assert options["services"] is None


def test_up_with_empty_service_option_dispatches_empty_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """显式给空选择（``--with ""``）必须传空元组：那是「清空」，不是「未指定」。"""
    options = _capture_up_options(monkeypatch, ["up", "--yes", "--with", ""])
    assert options["services"] == ()


def test_up_with_services_dispatches_normalized_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _capture_up_options(
        monkeypatch, ["up", "--yes", "--with", "firecrawl,searxng", "--with-searxng"]
    )
    assert options["services"] == ("firecrawl", "searxng")


def test_logs_positional_is_passed_through_not_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`deploy logs` 的位置参数是 compose 服务名，不能被当成 catalog 键。

    归一化会把 `undefined-bot`（CLI 自己的 help 举的例子）判成「未知服务」而
    恒失败；反过来 catalog 键 `firecrawl` 又不是合法的 compose 服务名。
    """
    layout = DeployLayout.under(tmp_path)
    layout.ensure()
    layout.compose_file.write_text("name: undefined-deploy\n", encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: tmp_path)

    seen: list[tuple[str, ...]] = []

    def fake_logs(
        run: object, invocation: object, *, services: tuple[str, ...], **kwargs: object
    ) -> docker_cli.CommandResult:
        del invocation, kwargs
        seen.append(tuple(services))
        return docker_cli.CommandResult(("docker",), 0, "", "")

    monkeypatch.setattr(docker_cli, "compose_logs", fake_logs)
    monkeypatch.setattr(
        docker_cli,
        "compose_ps",
        lambda run, invocation: docker_cli.CommandResult(("docker",), 0, "[]", ""),
    )

    assert cli.main(["logs", "undefined-bot", "firecrawl-api"]) == 0, (
        capsys.readouterr().out
    )
    assert seen == [("undefined-bot", "firecrawl-api")]
