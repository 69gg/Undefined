"""NagaAgent 子模块就绪检查与开关写入。

两个总闸的分工（源码依据 ``config/naga_policy.py``）：

- ``[features].nagaagent_mode_enabled`` —— NagaAgent AI 能力总闸：决定使用哪份
  系统提示词，以及是否把 ``naga_code_analysis_agent`` 暴露给模型。
- ``[naga].enabled`` —— 外部网关总闸（回调 API、``/naga`` 命令、绑定管理），
  还需 ``[api].enabled`` 同时成立。

本模块只负责「AI 能力」这一层：拉子模块时开能力、**始终关闭外部网关**，
避免用户在没准备 Naga 服务端的情况下把对外回调通道打开。

``naga_code_analysis_agent`` 的四个工具把 ``base_path`` 固定在
``Path.cwd()/"code"/"NagaAgent"``，所以能力开关与子模块存在性是绑定的——
子模块缺席时该 Agent 没有可用目标，因此两者由同一个问题决定。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Undefined.deploy.config_patch import PatchPlan

#: 子模块在 .gitmodules 中的路径名。
SUBMODULE_PATH = "code/NagaAgent"
GITMODULES_FILE = ".gitmodules"

#: git 命令超时（秒）：子模块拉取可能较慢，但不能无限等。
SUBMODULE_TIMEOUT_SECONDS = 600

#: 开启能力时写入的值。
ENABLED_VALUES: dict[str, Any] = {
    "features.nagaagent_mode_enabled": True,
    "naga.enabled": False,
    "naga.use_proxy": False,
    "naga.moderation_enabled": True,
    "naga.mode": "off",
    "naga.api_url": "",
    "naga.api_key": "",
}

#: 关闭时写入的值；``naga.*`` 全部归零，避免残留配置在下次开启时意外生效。
DISABLED_VALUES: dict[str, Any] = {
    "features.nagaagent_mode_enabled": False,
    "naga.enabled": False,
    "naga.mode": "off",
    "naga.api_url": "",
    "naga.api_key": "",
}

ABOUT: dict[str, str] = {
    "features.nagaagent_mode_enabled": "NagaAgent 问答能力总闸",
    "naga.enabled": "Naga 外部网关总闸（部署脚本始终关闭）",
    "naga.use_proxy": "Naga 网关是否走代理（网关关闭时无影响）",
    "naga.moderation_enabled": "Naga 外发消息审核（网关关闭时无影响）",
    "naga.mode": "Naga 会话级策略（off/blacklist/allowlist）",
    "naga.api_url": "Naga 服务端地址（不部署服务端时留空）",
    "naga.api_key": "Naga 共享密钥（不部署服务端时留空）",
}


@dataclass(frozen=True, slots=True)
class SubmoduleStatus:
    """``code/NagaAgent`` 的状态。"""

    declared: bool
    directory_exists: bool
    has_files: bool
    is_git_repo: bool

    @property
    def ready(self) -> bool:
        """子模块已初始化：目录存在且非空。"""
        return self.directory_exists and self.has_files

    def describe(self) -> str:
        if self.ready:
            return "已就绪"
        if not self.declared:
            return "仓库未声明该子模块"
        if not self.directory_exists:
            return "目录不存在"
        return "目录为空（子模块未初始化）"


def submodule_path(repo: Path) -> Path:
    return repo / SUBMODULE_PATH


def is_submodule_declared(repo: Path) -> bool:
    """``.gitmodules`` 是否在 ``path`` 上声明了该子模块（按行精确比对）。"""
    gitmodules = repo / GITMODULES_FILE
    if not gitmodules.is_file():
        return False
    try:
        text = gitmodules.read_text(encoding="utf-8")
    except OSError:
        return False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("path") and "=" in line:
            _, _, value = line.partition("=")
            if value.strip().strip('"') == SUBMODULE_PATH:
                return True
    return False


def inspect_submodule(repo: Path) -> SubmoduleStatus:
    """检查子模块当前状态（不执行任何 git 写操作）。"""
    path = submodule_path(repo)
    exists = path.is_dir()
    has_files = exists and any(path.iterdir())
    return SubmoduleStatus(
        declared=is_submodule_declared(repo),
        directory_exists=exists,
        has_files=has_files,
        is_git_repo=(path / ".git").exists(),
    )


def check_git_available() -> str | None:
    """返回 ``git`` 可执行文件路径；找不到返回 ``None``。"""
    from shutil import which

    return which("git")


def init_submodule_command() -> tuple[str, ...]:
    """初始化子模块的完整命令（也用于错误提示里让用户手动执行）。"""
    return ("git", "submodule", "update", "--init", "--recursive", SUBMODULE_PATH)


def ensure_submodule(repo: Path, *, status: SubmoduleStatus | None = None) -> str:
    """确保子模块已初始化。

    已就绪时是 no-op（不跑 git，避免每次 up 都触发网络与锁）。
    失败时抛 :class:`RuntimeError`，并把可手动执行的命令写在错误里——
    不静默继续，否则会生成一份「开了能力却没有目标代码」的配置。
    """
    current = status if status is not None else inspect_submodule(repo)
    if current.ready:
        return "already-ready"

    if not current.declared:
        raise RuntimeError(
            f"{GITMODULES_FILE} 未声明 {SUBMODULE_PATH}；"
            "请先按仓库说明初始化子模块，或改用 --no-nagaagent"
        )

    git = check_git_available()
    if git is None:
        raise RuntimeError(
            "找不到 git，无法自动拉取 NagaAgent 子模块；请手动执行："
            + " ".join(init_submodule_command())
        )

    command = init_submodule_command()
    try:
        completed = subprocess.run(
            command,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=SUBMODULE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"拉取 NagaAgent 子模块超时（{SUBMODULE_TIMEOUT_SECONDS}s）；"
            "请手动执行：" + " ".join(command)
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"执行 git 失败：{exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"退出码 {completed.returncode}"
        raise RuntimeError(
            "拉取 NagaAgent 子模块失败：" + tail + "；请手动执行：" + " ".join(command)
        )

    after = inspect_submodule(repo)
    if not after.ready:
        raise RuntimeError(
            f"子模块命令已执行但 {SUBMODULE_PATH} 仍为空；请检查网络或手动执行："
            + " ".join(command)
        )
    return "initialized"


def build_patch_plan(repo: Path, *, nagaagent: bool) -> PatchPlan:
    """生成 NagaAgent 相关的 config.toml 写入计划（纯函数，不碰磁盘）。"""
    values = ENABLED_VALUES if nagaagent else DISABLED_VALUES
    return PatchPlan(
        config_path=repo / "config.toml",
        desired=dict(values),
        about=dict(ABOUT),
    )


__all__ = [
    "ABOUT",
    "DISABLED_VALUES",
    "ENABLED_VALUES",
    "GITMODULES_FILE",
    "SUBMODULE_PATH",
    "SUBMODULE_TIMEOUT_SECONDS",
    "SubmoduleStatus",
    "build_patch_plan",
    "check_git_available",
    "ensure_submodule",
    "init_submodule_command",
    "inspect_submodule",
    "is_submodule_declared",
    "submodule_path",
]
