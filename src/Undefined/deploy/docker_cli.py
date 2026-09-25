"""docker / docker compose 调用层（本包唯一的进程外 I/O 边界）。

其余模块都是纯函数，便于单测；需要真正执行时统一走这里，好处是：
``--dry-run`` 只需要把 :class:`CommandRunner` 换成 :class:`DryRunRunner`。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from Undefined.deploy import catalog

DOCKER_BINARY = "docker"
COMPOSE_TIMEOUT_SECONDS = 900.0
CONFIG_TIMEOUT_SECONDS = 60.0
PULL_TIMEOUT_SECONDS = 3600.0

#: 镜像拉取策略：compose 的 ``--pull`` 取值。
PULL_MISSING = "missing"
PULL_ALWAYS = "always"
PULL_NEVER = "never"
PULL_POLICIES = (PULL_MISSING, PULL_ALWAYS, PULL_NEVER)


class DockerError(RuntimeError):
    """docker 命令不可用或执行失败。"""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """一次命令执行的结果。"""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def combined_output(self) -> str:
        return "\n".join(
            part for part in (self.stdout.strip(), self.stderr.strip()) if part
        )

    def summary(self) -> str:
        """失败时的单行摘要，取 stderr 最后一行更有信息量。"""
        lines = [line for line in self.stderr.strip().splitlines() if line.strip()]
        if lines:
            return lines[-1]
        lines = [line for line in self.stdout.strip().splitlines() if line.strip()]
        return lines[-1] if lines else f"退出码 {self.returncode}"


@dataclass(frozen=True, slots=True)
class DockerAvailability:
    """docker / docker compose 的可用性。"""

    docker_path: str | None
    compose_version: str | None

    @property
    def docker_available(self) -> bool:
        return self.docker_path is not None

    @property
    def compose_available(self) -> bool:
        return self.compose_version is not None

    @property
    def ok(self) -> bool:
        return self.docker_available and self.compose_available

    def describe(self) -> str:
        if not self.docker_available:
            return "找不到 docker 命令，请先安装 Docker Engine 或 Docker Desktop"
        if not self.compose_available:
            return "找不到 `docker compose` 插件（v2），请安装 docker-compose-plugin"
        return f"docker {self.docker_path}，compose {self.compose_version}"


def _which(command: str) -> str | None:
    return shutil.which(command)


def check_availability() -> DockerAvailability:
    """检查 docker 与 compose v2 插件（不抛错，供调用方决定怎么提示）。"""
    docker_path = _which(DOCKER_BINARY)
    compose_version: str | None = None
    if docker_path is not None:
        try:
            completed = subprocess.run(
                (docker_path, "compose", "version", "--short"),
                capture_output=True,
                text=True,
                timeout=CONFIG_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is not None and completed.returncode == 0:
            compose_version = completed.stdout.strip() or "unknown"
    return DockerAvailability(docker_path=docker_path, compose_version=compose_version)


def require_available() -> DockerAvailability:
    """检查不可用时直接抛 :class:`DockerError`。"""
    availability = check_availability()
    if not availability.ok:
        raise DockerError(availability.describe())
    return availability


@dataclass(slots=True)
class CommandRunner:
    """真实执行的 runner。"""

    cwd: Path | None = None
    echo: Callable[[str], None] = print
    _echo_commands: bool = True

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = COMPOSE_TIMEOUT_SECONDS,
        stream: bool = False,
    ) -> CommandResult:
        """执行命令；``stream=True`` 时不捕获输出（用于 ``logs -f``）。"""
        args = tuple(str(item) for item in argv)
        if self._echo_commands:
            self.echo("+ " + " ".join(args))
        try:
            if stream:
                completed = subprocess.run(
                    args,
                    cwd=str(self.cwd) if self.cwd else None,
                    timeout=timeout,
                    check=False,
                )
                return CommandResult(
                    argv=args,
                    returncode=completed.returncode,
                    stdout="",
                    stderr="",
                )
            captured = subprocess.run(
                args,
                cwd=str(self.cwd) if self.cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DockerError(f"命令超时（{timeout}s）：{' '.join(args)}") from exc
        except OSError as exc:
            raise DockerError(f"无法执行 {' '.join(args)}：{exc}") from exc

        return CommandResult(
            argv=args,
            returncode=captured.returncode,
            stdout=captured.stdout or "",
            stderr=captured.stderr or "",
        )


@dataclass(slots=True)
class DryRunRunner:
    """只记录命令、不执行的 runner，用于 ``--dry-run``。"""

    cwd: Path | None = None
    echo: Callable[[str], None] = print
    commands: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float | None = COMPOSE_TIMEOUT_SECONDS,
        stream: bool = False,
    ) -> CommandResult:
        del timeout
        args = tuple(str(item) for item in argv)
        self.commands.append(args)
        self.echo("[dry-run] " + " ".join(args))
        return CommandResult(
            argv=args, returncode=0, stdout="", stderr="", dry_run=True
        )


Runner = CommandRunner | DryRunRunner


# --------------------------------------------------------------------------- #
# compose 命令
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ComposeInvocation:
    """compose 调用所需的文件与环境参数。"""

    compose_file: Path
    env_file: Path
    project_name: str = catalog.COMPOSE_PROJECT_NAME
    extra_env_file: Path | None = None

    def base_argv(self) -> list[str]:
        argv = [
            DOCKER_BINARY,
            "compose",
            "--project-name",
            self.project_name,
            "--env-file",
            str(self.env_file),
            "--project-directory",
            str(self.compose_file.parent),
            "-f",
            str(self.compose_file),
        ]
        if self.extra_env_file is not None:
            argv.extend(["--env-file", str(self.extra_env_file)])
        return argv


def compose_up(
    runner: Runner,
    invocation: ComposeInvocation,
    *,
    pull: str = PULL_MISSING,
) -> CommandResult:
    if pull not in PULL_POLICIES:
        raise DockerError(f"未知拉取策略 {pull!r}；可选 {', '.join(PULL_POLICIES)}")
    argv = [
        *invocation.base_argv(),
        "up",
        "-d",
        "--remove-orphans",
        "--pull",
        pull,
    ]
    return runner.run(argv)


def compose_down(
    runner: Runner,
    invocation: ComposeInvocation,
    *,
    remove_volumes: bool = False,
) -> CommandResult:
    argv = [*invocation.base_argv(), "down", "--remove-orphans"]
    if remove_volumes:
        argv.append("--volumes")
    return runner.run(argv)


def compose_ps(runner: Runner, invocation: ComposeInvocation) -> CommandResult:
    argv = [*invocation.base_argv(), "ps", "--format", "json"]
    return runner.run(argv, timeout=CONFIG_TIMEOUT_SECONDS)


def compose_config(runner: Runner, invocation: ComposeInvocation) -> CommandResult:
    """解析并校验 compose 文件（不拉镜像、不启动容器）。"""
    argv = [*invocation.base_argv(), "config", "--quiet"]
    return runner.run(argv, timeout=CONFIG_TIMEOUT_SECONDS)


def compose_logs(
    runner: Runner,
    invocation: ComposeInvocation,
    *,
    services: Sequence[str] = (),
    tail: int | None = None,
    follow: bool = True,
) -> CommandResult:
    argv = [*invocation.base_argv(), "logs"]
    if follow:
        argv.append("--follow")
    if tail is not None:
        argv.extend(["--tail", str(tail)])
    argv.extend(services)
    return runner.run(argv, timeout=None, stream=follow)


def compose_service_names(runner: Runner, invocation: ComposeInvocation) -> set[str]:
    """从 ``compose config`` 结果里取出服务名，用于校验与展示。"""
    result = runner.run(
        [*invocation.base_argv(), "config", "--services"],
        timeout=CONFIG_TIMEOUT_SECONDS,
    )
    if not result.ok:
        raise DockerError(f"读取 compose 服务列表失败：{result.summary()}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


__all__ = [
    "CONFIG_TIMEOUT_SECONDS",
    "COMPOSE_TIMEOUT_SECONDS",
    "CommandResult",
    "CommandRunner",
    "ComposeInvocation",
    "DOCKER_BINARY",
    "DockerAvailability",
    "DockerError",
    "DryRunRunner",
    "PULL_ALWAYS",
    "PULL_MISSING",
    "PULL_NEVER",
    "PULL_POLICIES",
    "PULL_TIMEOUT_SECONDS",
    "Runner",
    "check_availability",
    "compose_config",
    "compose_down",
    "compose_logs",
    "compose_ps",
    "compose_service_names",
    "compose_up",
    "require_available",
]
