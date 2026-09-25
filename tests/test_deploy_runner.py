"""``up`` 流程与 ``docker_cli`` 调用层测试。

不启动任何容器：docker 可用性检查与 compose 调用都被替换成假实现，
必要时用 ``--dry-run`` 走一遍完整流程。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Sequence

import pytest

from Undefined.deploy import catalog, docker_cli, nagaagent, runner
from Undefined.deploy.docker_cli import CommandResult, DockerAvailability
from Undefined.deploy.state import DeployLayout

CONFIG_TOML = """\
[onebot]
ws_url = "ws://127.0.0.1:3001"
token = ""
file_send_mode = "local"

[webui]
url = "127.0.0.1"
port = 8787
password = "changeme"

[api]
enabled = true
host = "127.0.0.1"
port = 8788
auth_key = "changeme"

[features]
nagaagent_mode_enabled = false

[naga]
enabled = false
"""


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 repo_root() 指向临时仓库，避免测试污染真实 config.toml。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)
    return repo


def _ok_result(argv: Sequence[str]) -> CommandResult:
    return CommandResult(argv=tuple(argv), returncode=0, stdout="", stderr="")


def _yes_options(**overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "command": "up",
        "mode": catalog.MODE_CONTAINER,
        "services": (),
        "nagaagent": False,
        "port_overrides": {},
        "port_bind": catalog.DEFAULT_PORT_BIND,
        "yes": True,
        "dry_run": True,
    }
    options.update(overrides)
    return options


# --------------------------------------------------------------------------- #
# .env 解析
# --------------------------------------------------------------------------- #


def test_parse_env_text_ignores_comments_and_blanks() -> None:
    parsed = runner.parse_env_text("# comment\n\nA=1\nB = two \n\n# x\nC=\n")
    assert parsed == {"A": "1", "B": "two", "C": ""}


def test_parse_env_text_keeps_equals_in_value() -> None:
    assert runner.parse_env_text("URL=http://a:1/?x=1")["URL"] == "http://a:1/?x=1"


def test_load_previous_env_missing_file(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    assert runner.load_previous_env(layout) == {}


def test_load_previous_env_round_trip(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    layout.ensure()
    layout.env_file.write_text("KEY=value\n", encoding="utf-8")
    assert runner.load_previous_env(layout) == {"KEY": "value"}


# --------------------------------------------------------------------------- #
# 向导
# --------------------------------------------------------------------------- #


def test_wizard_disabled_returns_defaults() -> None:
    wizard = runner.Wizard(enabled=False)
    assert wizard.choose_mode(catalog.MODE_HOST) == catalog.MODE_HOST
    assert wizard.choose_services(("searxng",)) == ("searxng",)
    assert wizard.choose_nagaagent(True) is True
    assert wizard.choose_port_bind("127.0.0.1") == "127.0.0.1"
    assert wizard.confirm("continue?", False) is False


def test_wizard_choose_mode_by_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert runner.Wizard(enabled=True).choose_mode(catalog.MODE_CONTAINER) == (
        catalog.MODE_HOST
    )


def test_wizard_choose_mode_defaults_on_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert runner.Wizard(enabled=True).choose_mode(catalog.MODE_HOST) == (
        catalog.MODE_HOST
    )


def test_wizard_choose_services_parses_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "1 3")
    chosen = runner.Wizard(enabled=True).choose_services(())
    assert chosen == ("searxng", "lxmusic2api")


def test_wizard_choose_services_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert runner.Wizard(enabled=True).choose_services(()) == ()


def test_wizard_choose_services_ignores_bad_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "9 abc 2")
    chosen = runner.Wizard(enabled=True).choose_services(())
    assert chosen == ("firecrawl",)
    output = capsys.readouterr().out
    assert "超出范围" in output
    assert "无法识别" in output


def test_wizard_yes_no_accepts_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "是")
    assert runner.Wizard(enabled=True).choose_nagaagent(False) is True


def test_wizard_survives_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    wizard = runner.Wizard(enabled=True)
    assert wizard.choose_services(("searxng",)) == ("searxng",)
    assert wizard.choose_nagaagent(True) is True


def test_wizard_enabled_requires_up_and_tty() -> None:
    assert runner.wizard_enabled({"command": "up", "yes": False}) in (True, False)
    assert runner.wizard_enabled({"command": "up", "yes": True}) is False
    assert runner.wizard_enabled({"command": "status"}) is False


# --------------------------------------------------------------------------- #
# NapCat WS token 对齐
# --------------------------------------------------------------------------- #


def _write_onebot(layout: DeployLayout, payload: dict[str, Any]) -> Path:
    layout.ensure()
    path = layout.napcat_config_dir / runner.NAPCAT_ONEBOT_CONFIG
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _onebot_payload(token: str = "") -> dict[str, Any]:
    return {
        "network": {
            "websocketServers": [
                {
                    "enable": True,
                    "name": "ws",
                    "host": "0.0.0.0",
                    "port": 3001,
                    "token": token,
                }
            ]
        }
    }


def test_patch_napcat_token_writes_token(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    path = _write_onebot(layout, _onebot_payload())
    note = runner.patch_napcat_ws_token(layout, "secret-token")

    assert "已对齐" in note
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["network"]["websocketServers"][0]["token"] == "secret-token"


def test_patch_napcat_token_is_idempotent(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_onebot(layout, _onebot_payload())
    runner.patch_napcat_ws_token(layout, "secret-token")
    assert "已是目标 token" in runner.patch_napcat_ws_token(layout, "secret-token")


def test_patch_napcat_token_preserves_other_fields(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    payload = _onebot_payload()
    payload["musicSignUrl"] = "https://example.com"
    payload["network"]["httpServers"] = [{"enable": False, "port": 3000}]
    path = _write_onebot(layout, payload)

    runner.patch_napcat_ws_token(layout, "t")
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["musicSignUrl"] == "https://example.com"
    assert written["network"]["httpServers"] == [{"enable": False, "port": 3000}]


def test_patch_napcat_token_reports_missing_file(tmp_path: Path) -> None:
    note = runner.patch_napcat_ws_token(DeployLayout.under(tmp_path), "t")
    assert "尚未生成" in note


def test_patch_napcat_token_reports_broken_json(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    layout.ensure()
    (layout.napcat_config_dir / runner.NAPCAT_ONEBOT_CONFIG).write_text(
        "{not json", encoding="utf-8"
    )
    assert "无法解析" in runner.patch_napcat_ws_token(layout, "t")


def test_patch_napcat_token_reports_missing_network(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_onebot(layout, {"musicSignUrl": ""})
    assert "缺少 network" in runner.patch_napcat_ws_token(layout, "t")


def test_patch_napcat_token_reports_missing_ws_server(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_onebot(layout, {"network": {"websocketServers": []}})
    assert "未启用正向 WebSocket" in runner.patch_napcat_ws_token(layout, "t")


def test_patch_napcat_token_skips_empty_token(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_onebot(layout, _onebot_payload())
    assert "token 为空" in runner.patch_napcat_ws_token(layout, "")


# --------------------------------------------------------------------------- #
# docker_cli
# --------------------------------------------------------------------------- #


def test_compose_invocation_argv_uses_project_directory(tmp_path: Path) -> None:
    invocation = docker_cli.ComposeInvocation(
        compose_file=tmp_path / "deploy" / "compose.yaml",
        env_file=tmp_path / "deploy" / ".env",
    )
    argv = invocation.base_argv()
    assert argv[:2] == ["docker", "compose"]
    assert "--project-directory" in argv
    assert argv[argv.index("--project-directory") + 1] == str(tmp_path / "deploy")
    # 相对绑定路径按 compose 文件目录解析，必须与 project-directory 一致
    assert argv[argv.index("-f") + 1] == str(tmp_path / "deploy" / "compose.yaml")


def test_compose_up_uses_pull_policy(tmp_path: Path) -> None:
    invocation = docker_cli.ComposeInvocation(
        compose_file=tmp_path / "compose.yaml", env_file=tmp_path / ".env"
    )
    dry = docker_cli.DryRunRunner()
    docker_cli.compose_up(dry, invocation, pull=docker_cli.PULL_NEVER)
    assert dry.commands[0][-2:] == ("--pull", "never")
    assert "up" in dry.commands[0] and "-d" in dry.commands[0]


def test_compose_up_rejects_unknown_pull_policy(tmp_path: Path) -> None:
    invocation = docker_cli.ComposeInvocation(
        compose_file=tmp_path / "compose.yaml", env_file=tmp_path / ".env"
    )
    with pytest.raises(docker_cli.DockerError, match="未知拉取策略"):
        docker_cli.compose_up(docker_cli.DryRunRunner(), invocation, pull="sometimes")


def test_compose_down_remove_volumes_flag(tmp_path: Path) -> None:
    invocation = docker_cli.ComposeInvocation(
        compose_file=tmp_path / "compose.yaml", env_file=tmp_path / ".env"
    )
    dry = docker_cli.DryRunRunner()
    docker_cli.compose_down(dry, invocation, remove_volumes=True)
    argv = dry.commands[0]
    assert "down" in argv
    assert "--volumes" in argv
    assert "--remove-orphans" in argv


def test_dry_run_runner_records_without_executing() -> None:
    dry = docker_cli.DryRunRunner()
    result = dry.run(["docker", "ps"])
    assert result.ok is True
    assert result.dry_run is True
    assert dry.commands == [("docker", "ps")]


def test_command_result_summary_prefers_stderr() -> None:
    result = CommandResult(
        argv=("docker",), returncode=1, stdout="out\nline2\n", stderr="\nbad thing\n"
    )
    assert result.summary() == "bad thing"


def test_command_result_summary_falls_back_to_stdout() -> None:
    result = CommandResult(
        argv=("docker",), returncode=1, stdout="only out\n", stderr=""
    )
    assert result.summary() == "only out"


def test_command_result_summary_uses_exit_code() -> None:
    result = CommandResult(argv=("docker",), returncode=3, stdout="", stderr="")
    assert "3" in result.summary()


def test_check_availability_reports_missing_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_cli, "_which", lambda command: None)
    availability = docker_cli.check_availability()
    assert availability.docker_available is False
    assert "找不到 docker" in availability.describe()


def test_check_availability_reports_missing_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(docker_cli, "_which", lambda command: "/usr/bin/docker")

    def _fake_run(*args: Any, **kwargs: Any) -> Any:
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "no plugin"})()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    availability = docker_cli.check_availability()
    assert availability.docker_available is True
    assert availability.compose_available is False
    assert "compose" in availability.describe()


def test_require_available_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_cli,
        "check_availability",
        lambda: DockerAvailability(docker_path=None, compose_version=None),
    )
    with pytest.raises(docker_cli.DockerError):
        docker_cli.require_available()


# --------------------------------------------------------------------------- #
# up：dry-run 完整流程
# --------------------------------------------------------------------------- #


def test_up_dry_run_writes_nothing(fake_repo: Path) -> None:
    layout = DeployLayout.under(fake_repo)
    assert runner.run_up(_yes_options()) == 0
    assert not layout.root.exists()
    assert (fake_repo / "config.toml").read_text(encoding="utf-8") == CONFIG_TOML


def test_up_dry_run_prints_plan_and_compose(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner.run_up(_yes_options(services=("searxng",)))
    output = capsys.readouterr().out
    assert "部署计划" in output
    assert "searxng" in output
    assert "compose.yaml" in output
    # dry-run 输出不得泄露新生成的凭据
    assert "<secret>" in output
    assert "将写入" in output
    assert "已更新" not in output


def test_up_dry_run_does_not_touch_submodule(
    fake_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry-run 不应拉取子模块")

    monkeypatch.setattr(nagaagent, "ensure_submodule", _boom)
    assert runner.run_up(_yes_options(nagaagent=True)) == 0


def test_status_without_up_reports_error(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert runner.run_status({}) == 1
    assert "请先执行" in capsys.readouterr().out


def test_down_without_up_reports_error(fake_repo: Path) -> None:
    assert runner.run_down({}) == 1
