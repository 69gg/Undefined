"""``up`` 流程与 ``docker_cli`` 调用层测试。

不启动任何容器：docker 可用性检查与 compose 调用都被替换成假实现，
必要时用 ``--dry-run`` 走一遍完整流程。
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Sequence

import pytest
import yaml

from Undefined.deploy import catalog, docker_cli, generate, nagaagent, runner
from Undefined.deploy.docker_cli import CommandResult, DockerAvailability
from Undefined.deploy.state import DeployLayout, read_state

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
        # 与真实 CLI 一致：未显式传 --port-bind 时为 None，
        # 这样 run_up 才会回退到「上次的选择」（显式传值应当覆盖）。
        "port_bind": None,
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
# NapCat WS 配置（生成的模板文件，而非启动后补写）
# --------------------------------------------------------------------------- #


def _ws_payload(token: str = "t" * 24, port: int = 3001) -> dict[str, Any]:
    return {
        "network": {
            "websocketServers": [
                {
                    "enable": True,
                    "name": "ws",
                    "host": "0.0.0.0",
                    "port": port,
                    "token": token,
                }
            ]
        }
    }


def _write_ws(layout: DeployLayout, payload: dict[str, Any]) -> Path:
    layout.ensure()
    path = layout.napcat_dir / generate.NAPCAT_WS_ARTIFACT
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_verify_napcat_ws_config_accepts_matching_artifact(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_ws(layout, _ws_payload())
    note = runner.verify_napcat_ws_config(layout, "t" * 24)
    assert "已就绪" in note
    assert "3001" in note


def test_verify_napcat_ws_config_reports_missing_file(tmp_path: Path) -> None:
    note = runner.verify_napcat_ws_config(DeployLayout.under(tmp_path), "t" * 24)
    assert "缺失" in note


def test_verify_napcat_ws_config_reports_broken_json(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    layout.ensure()
    (layout.napcat_dir / generate.NAPCAT_WS_ARTIFACT).write_text(
        "{not json", encoding="utf-8"
    )
    assert "无法解析" in runner.verify_napcat_ws_config(layout, "t" * 24)


def test_verify_napcat_ws_config_reports_missing_ws_server(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_ws(layout, {"network": {"websocketServers": []}})
    assert "结构异常" in runner.verify_napcat_ws_config(layout, "t" * 24)


def test_verify_napcat_ws_config_reports_token_mismatch(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_ws(layout, _ws_payload(token="other-token"))
    assert "token 不符" in runner.verify_napcat_ws_config(layout, "t" * 24)


def test_verify_napcat_ws_config_reports_port_mismatch(tmp_path: Path) -> None:
    layout = DeployLayout.under(tmp_path)
    _write_ws(layout, _ws_payload(port=9999))
    assert "端口不符" in runner.verify_napcat_ws_config(layout, "t" * 24)


def test_ws_artifact_is_mounted_over_the_image_template(tmp_path: Path) -> None:
    """挂载必须指向镜像的 /app/templates/ws.json，入口才会拷到配置。

    只挂单个文件而不是整个目录，避免遮蔽镜像里其它 MODE 模板。
    """
    ctx = generate.GenerateContext(
        repo=tmp_path,
        layout=DeployLayout.under(tmp_path),
        mode=catalog.MODE_CONTAINER,
    )
    services = yaml.safe_load(generate.build(ctx).compose_text)["services"]
    volumes = services["napcat"]["volumes"]
    assert (
        f"./napcat/{generate.NAPCAT_WS_ARTIFACT}:/app/templates/ws.json:ro" in volumes
    )
    # 不能整个目录覆盖
    assert not [v for v in volumes if v.endswith(":/app/templates:ro")]


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


def _stub_docker(monkeypatch: pytest.MonkeyPatch, *, stub_verify: bool = True) -> None:
    """桩掉真实 docker 调用，让 run_up 能走到写盘之后。"""
    monkeypatch.setattr(
        docker_cli,
        "check_availability",
        lambda: DockerAvailability("/usr/bin/docker", "2.30.0"),
    )
    monkeypatch.setattr(
        docker_cli,
        "compose_config",
        lambda run, invocation: CommandResult(("docker",), 0, "", ""),
    )
    monkeypatch.setattr(
        docker_cli,
        "compose_up",
        lambda run, invocation, pull="missing": CommandResult(("docker",), 0, "", ""),
    )
    if stub_verify:
        monkeypatch.setattr(
            runner, "verify_napcat_ws_config", lambda layout, token: "已就绪"
        )


def test_up_creates_full_config_from_example_on_fresh_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全新 clone（无 config.toml）必须先落一份完整配置再打补丁。

    否则只会渲染被 patch 的少数键，生成出来的文件没有 [models]/[core]，
    而文档却让用户去填 [models.*]。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)
    _stub_docker(monkeypatch)

    assert not (repo / "config.toml").exists()
    assert runner.run_up(_yes_options(dry_run=False)) == 0

    created = repo / "config.toml"
    assert created.is_file(), "应已从 config.toml.example 生成 config.toml"
    parsed = tomllib.loads(created.read_text(encoding="utf-8"))
    # 示例里的段落都在，而不是只有被 patch 的那几个键
    for section in ("onebot", "webui", "api", "features", "naga"):
        assert section in parsed, f"生成的 config.toml 缺少 [{section}]"


def test_dry_run_does_not_create_config_on_fresh_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--dry-run 连「从示例复制」都不做。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)

    assert runner.run_up(_yes_options()) == 0
    assert not (repo / "config.toml").exists()


def test_up_keeps_existing_config_untouched_on_dry_run(
    fake_repo: Path,
) -> None:
    original = (fake_repo / "config.toml").read_text(encoding="utf-8")
    assert runner.run_up(_yes_options()) == 0
    assert (fake_repo / "config.toml").read_text(encoding="utf-8") == original


def test_ports_and_bind_survive_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """重跑 up 必须沿用上次的端口与绑定地址。

    旧实现只把 ports 写进 STATE.json 却从不读回，第二次不带参数运行会把
    --port 与 --port-bind 静默退回默认值（0.0.0.0 退回回环 = 远程访问无声中断）。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)
    _stub_docker(monkeypatch)

    first = _yes_options(
        dry_run=False,
        port_overrides={"bot_webui": 19000, "napcat_ws": 13001},
        port_bind="0.0.0.0",
    )
    assert runner.run_up(first) == 0
    layout = DeployLayout.under(repo)
    env_after_first = runner.load_previous_env(layout)
    state = read_state(layout)
    assert state is not None
    assert state.port_bind == "0.0.0.0", (
        f"第一次 up 未持久化 port_bind：{state.port_bind!r}"
    )

    # 第二次完全不带端口参数
    capsys.readouterr()
    assert runner.run_up(_yes_options(dry_run=False)) == 0
    env_after_second = runner.load_previous_env(layout)

    for key in (
        "UNDEFINED_DEPLOY_PORT_BOT_WEBUI",
        "UNDEFINED_DEPLOY_PORT_NAPCAT_WS",
        "UNDEFINED_DEPLOY_PORT_BOT_WEBUI_BIND",
    ):
        assert env_after_first[key] == env_after_second[key], f"{key} 在重跑时被回退"
    assert env_after_second["UNDEFINED_DEPLOY_PORT_BOT_WEBUI"] == "19000"
    assert env_after_second["UNDEFINED_DEPLOY_PORT_BOT_WEBUI_BIND"] == "0.0.0.0"
    assert state.port_bind == "0.0.0.0"


def test_ws_artifact_carries_token_and_port_after_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """up 结束时应已生成带 token 的 ws.json（不再依赖启动后补写）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)
    # 注意：本用例要检查真实写出的 ws.json，所以只桩 docker，不桩 verify_napcat_ws_config
    _stub_docker(monkeypatch, stub_verify=False)

    assert runner.run_up(_yes_options(dry_run=False)) == 0
    layout = DeployLayout.under(repo)
    artifact = layout.napcat_dir / generate.NAPCAT_WS_ARTIFACT
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    server = payload["network"]["websocketServers"][0]
    token = runner.load_previous_env(layout)["UNDEFINED_DEPLOY_NAPCAT_WS_TOKEN"]
    assert server["token"] == token
    assert server["port"] == catalog.NAPCAT_WS_CONTAINER_PORT


def test_empty_with_clears_previous_service_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--with ""` 必须能非交互地取消已选服务（空元组 = 显式清空）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml.example").write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setattr(runner, "repo_root", lambda: repo)
    _stub_docker(monkeypatch)

    assert runner.run_up(_yes_options(services=("searxng",), dry_run=False)) == 0
    layout = DeployLayout.under(repo)
    state = read_state(layout)
    assert state is not None and state.services == ("searxng",)

    # 显式清空：空元组而非 None
    assert runner.run_up(_yes_options(services=(), dry_run=False)) == 0
    state = read_state(layout)
    assert state is not None
    assert state.services == (), "空元组应清空上次选择，而不是沿用"


def test_lxmusic2api_config_is_owner_only(tmp_path: Path) -> None:
    """桥接服务的 config.toml 含 api_key，应收紧到属主可读。"""
    import stat

    layout = DeployLayout.under(tmp_path)
    config = generate.build(
        generate.GenerateContext(
            repo=tmp_path,
            layout=layout,
            mode=catalog.MODE_CONTAINER,
            services=(catalog.LXMUSIC2API.key,),
        )
    )
    assert config.lxmusic2api_config is not None

    layout.ensure()
    runner.write_generated(layout, config)
    mode = stat.S_IMODE((layout.lxmusic2api_dir / "config.toml").stat().st_mode)
    if os.name == "posix":
        assert mode == 0o600, oct(mode)


def test_status_without_up_reports_error(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert runner.run_status({}) == 1
    assert "请先执行" in capsys.readouterr().out


def test_down_without_up_reports_error(fake_repo: Path) -> None:
    assert runner.run_down({}) == 1
