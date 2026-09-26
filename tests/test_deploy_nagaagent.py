"""NagaAgent 子模块检查与开关写入测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from Undefined.deploy import config_patch, nagaagent

GITMODULES = """\
[submodule "code/NagaAgent"]
\tpath = code/NagaAgent
\turl = https://github.com/Xxiii8322766509/NagaAgent.git
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitmodules").write_text(GITMODULES, encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# 状态检查
# --------------------------------------------------------------------------- #


def test_declared_when_gitmodules_has_the_path(repo: Path) -> None:
    assert nagaagent.is_submodule_declared(repo) is True
    assert nagaagent.is_submodule_declared(repo / "nope") is False


def test_declared_matches_path_exactly(repo: Path) -> None:
    """``code/NagaAgent2`` 不能被当成 ``code/NagaAgent``。"""
    (repo / ".gitmodules").write_text(
        '[submodule "x"]\n\tpath = code/NagaAgent2\n', encoding="utf-8"
    )
    assert nagaagent.is_submodule_declared(repo) is False


def test_inspect_reports_missing_directory(repo: Path) -> None:
    status = nagaagent.inspect_submodule(repo)
    assert status.declared is True
    assert status.directory_exists is False
    assert status.ready is False
    assert "不存在" in status.describe()


def test_inspect_reports_empty_directory(repo: Path) -> None:
    nagaagent.submodule_path(repo).mkdir(parents=True)
    status = nagaagent.inspect_submodule(repo)
    assert status.directory_exists is True
    assert status.has_files is False
    assert status.ready is False
    assert "未初始化" in status.describe()


def test_inspect_reports_ready(repo: Path) -> None:
    target = nagaagent.submodule_path(repo)
    target.mkdir(parents=True)
    (target / "main.py").write_text("print('hi')\n", encoding="utf-8")
    status = nagaagent.inspect_submodule(repo)
    assert status.ready is True
    assert status.describe() == "已就绪"


def test_inspect_handles_undeclared_submodule(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    status = nagaagent.inspect_submodule(root)
    assert status.declared is False
    assert "未声明" in status.describe()


# --------------------------------------------------------------------------- #
# 拉取
# --------------------------------------------------------------------------- #


def test_ensure_submodule_is_noop_when_ready(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已就绪时绝不能跑 git：每次 up 都拉一次会带来网络与锁开销。"""
    target = nagaagent.submodule_path(repo)
    target.mkdir(parents=True)
    (target / "main.py").write_text("x\n", encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("已就绪时不应执行 git")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert nagaagent.ensure_submodule(repo) == "already-ready"


def test_ensure_submodule_raises_when_undeclared(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    with pytest.raises(RuntimeError, match="未声明"):
        nagaagent.ensure_submodule(root)


def test_ensure_submodule_raises_without_git(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nagaagent, "check_git_available", lambda: None)
    with pytest.raises(RuntimeError, match="找不到 git") as excinfo:
        nagaagent.ensure_submodule(repo)
    # 错误里要给出可手动执行的命令
    assert "git submodule update --init --recursive code/NagaAgent" in str(
        excinfo.value
    )


def test_ensure_submodule_runs_git_when_missing(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def _fake_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        target = nagaagent.submodule_path(repo)
        target.mkdir(parents=True, exist_ok=True)
        (target / "main.py").write_text("x\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(nagaagent, "check_git_available", lambda: "/usr/bin/git")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert nagaagent.ensure_submodule(repo) == "initialized"
    assert calls == [nagaagent.init_submodule_command()]


def test_ensure_submodule_reports_git_failure(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "fatal: could not read\n")

    monkeypatch.setattr(nagaagent, "check_git_available", lambda: "/usr/bin/git")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="could not read") as excinfo:
        nagaagent.ensure_submodule(repo)
    assert "git submodule update --init --recursive code/NagaAgent" in str(
        excinfo.value
    )


def test_ensure_submodule_reports_timeout(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run(command: tuple[str, ...], **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    monkeypatch.setattr(nagaagent, "check_git_available", lambda: "/usr/bin/git")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="超时"):
        nagaagent.ensure_submodule(repo)


def test_ensure_submodule_reports_still_empty(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """git 报成功但目录仍空时必须失败，不能继续生成配置。"""

    def _fake_run(
        command: tuple[str, ...], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(nagaagent, "check_git_available", lambda: "/usr/bin/git")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(RuntimeError, match="仍为空"):
        nagaagent.ensure_submodule(repo)


# --------------------------------------------------------------------------- #
# 开关写入
# --------------------------------------------------------------------------- #


def test_enabled_plan_only_opens_the_capability_switch(repo: Path) -> None:
    """开启分支只写能力总闸，一个 [naga] 键都不产出。

    用精确相等而不是 ``desired.get(key, "") == ""``：后者在键存在与不存在时
    都通过，正是它让「凭据被写成空串」这种破坏性行为一路绿灯。
    """
    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    assert plan.desired == {"features.nagaagent_mode_enabled": True}


def test_disabled_plan_only_closes_the_capability_switch(repo: Path) -> None:
    plan = nagaagent.build_patch_plan(repo, nagaagent=False)
    assert plan.desired == {"features.nagaagent_mode_enabled": False}


def test_enabled_plan_preserves_user_gateway_config(tmp_path: Path) -> None:
    """回归：用户已填非空凭据时，开启分支曾把它们覆写成空串并关掉网关。

    这条必须走真实的 apply_plan + 重新读取，才能证明「写盘后用户的 [naga]
    配置原样保留」——只断言 plan.desired 的形状不足以覆盖这条路径。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / "config.toml"
    config.write_text(
        "[features]\nnagaagent_mode_enabled = false\n\n"
        "[naga]\nenabled = true\n"
        'api_url = "https://naga.example.com"\n'
        'api_key = "gateway-key"\n'
        'mode = "allowlist"\n',
        encoding="utf-8",
    )

    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    config_patch.apply_plan(
        plan,
        example_path=repo / "config.toml.example",
        backup_dir=tmp_path / "backup",
    )

    data = config_patch.load_toml(config)
    assert data["features"]["nagaagent_mode_enabled"] is True
    assert data["naga"]["enabled"] is True
    assert data["naga"]["api_url"] == "https://naga.example.com"
    assert data["naga"]["api_key"] == "gateway-key"
    assert data["naga"]["mode"] == "allowlist"


def test_disabled_plan_preserves_existing_gateway_credentials(tmp_path: Path) -> None:
    """已配置过 Naga 网关的仓库，默认部署后凭据、模式与总闸都必须原样保留。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / "config.toml"
    config.write_text(
        "[features]\nnagaagent_mode_enabled = true\n\n"
        "[naga]\nenabled = true\n"
        'api_url = "https://naga.example.com"\n'
        'api_key = "gateway-key"\n'
        'mode = "allowlist"\n',
        encoding="utf-8",
    )

    plan = nagaagent.build_patch_plan(repo, nagaagent=False)
    config_patch.apply_plan(
        plan,
        example_path=repo / "config.toml.example",
        backup_dir=tmp_path / "backup",
    )

    data = config_patch.load_toml(config)
    assert data["features"]["nagaagent_mode_enabled"] is False
    # 用户自己开着的网关不能被默认部署关掉
    assert data["naga"]["enabled"] is True
    assert data["naga"]["api_url"] == "https://naga.example.com"
    assert data["naga"]["mode"] == "allowlist"


def test_plan_targets_repo_config(repo: Path) -> None:
    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    assert plan.config_path == repo / "config.toml"


def test_plan_provides_about_for_every_key(repo: Path) -> None:
    for flag in (True, False):
        plan = nagaagent.build_patch_plan(repo, nagaagent=flag)
        for key in plan.desired:
            assert plan.about.get(key), f"{key} 缺少说明"
