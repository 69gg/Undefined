"""NagaAgent 子模块检查与开关写入测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from Undefined.deploy import nagaagent

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


def test_enabled_plan_opens_qa_but_keeps_gateway_closed(repo: Path) -> None:
    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    assert plan.desired["features.nagaagent_mode_enabled"] is True
    # 关键约束：能力开启，但外部网关总闸不打开
    assert plan.desired["naga.enabled"] is False
    # 凭据留空只对「本来就缺失」有意义；此处 config.toml 不存在，
    # 因此空值不会成为差异项（apply_plan 会跳过无差异的键）
    assert plan.desired.get("naga.api_url", "") == ""
    assert plan.desired.get("naga.api_key", "") == ""


def test_enabled_plan_clears_placeholder_credentials(tmp_path: Path) -> None:
    """配置里存在空串占位时，开启分支应把它们归一为空（而不是留下占位）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml").write_text(
        '[naga]\napi_url = ""\napi_key = "REPLACE_ME"\n', encoding="utf-8"
    )
    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    assert plan.desired["naga.enabled"] is False
    # api_url 已是空串 -> 无差异，不写入
    assert plan.desired.get("naga.api_url", "") == ""


def test_disabled_plan_only_closes_the_master_switches(repo: Path) -> None:
    """关闭分支只关两个总闸，不得清空用户的 Naga 服务端凭据。

    ``naga.api_url`` / ``api_key`` / ``mode`` 是用户已对接好的配置；网关总闸一关
    它们本就不生效，默认部署没有理由抹掉（曾因无条件清空而被审查判为破坏性行为）。
    """
    plan = nagaagent.build_patch_plan(repo, nagaagent=False)
    assert plan.desired["features.nagaagent_mode_enabled"] is False
    assert plan.desired["naga.enabled"] is False
    for key in ("naga.api_url", "naga.api_key", "naga.mode"):
        assert key not in plan.desired, f"{key} 不应出现在关闭分支"


def test_disabled_plan_preserves_existing_gateway_credentials(tmp_path: Path) -> None:
    """已配置过 Naga 网关的仓库，默认部署后凭据与模式必须原样保留。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.toml").write_text(
        "[features]\nnagaagent_mode_enabled = true\n\n"
        "[naga]\nenabled = true\n"
        'api_url = "https://naga.example.com"\n'
        'api_key = "gateway-key"\n'
        'mode = "allowlist"\n',
        encoding="utf-8",
    )

    plan = nagaagent.build_patch_plan(repo, nagaagent=False)
    assert "naga.api_url" not in plan.desired
    assert "naga.api_key" not in plan.desired
    assert "naga.mode" not in plan.desired


def test_gateway_is_closed_in_both_branches(repo: Path) -> None:
    for flag in (True, False):
        plan = nagaagent.build_patch_plan(repo, nagaagent=flag)
        assert plan.desired["naga.enabled"] is False


def test_plan_targets_repo_config(repo: Path) -> None:
    plan = nagaagent.build_patch_plan(repo, nagaagent=True)
    assert plan.config_path == repo / "config.toml"


def test_plan_provides_about_for_every_key(repo: Path) -> None:
    for flag in (True, False):
        plan = nagaagent.build_patch_plan(repo, nagaagent=flag)
        for key in plan.desired:
            assert plan.about.get(key), f"{key} 缺少说明"


def test_disabled_plan_does_not_define_gateway_only_keys(repo: Path) -> None:
    """关闭分支不该写入 use_proxy / moderation_enabled 这类网关专属项。"""
    plan = nagaagent.build_patch_plan(repo, nagaagent=False)
    assert "naga.use_proxy" not in plan.desired
    assert "naga.moderation_enabled" not in plan.desired
