"""部署运行态目录与状态文件。

布局约定：模板放在包内 ``templates/``（随 wheel 分发），运行态一律落在仓库根的
``deploy/``（gitignored）。状态文件只做“记录与幂等依据”，不缓存可推导内容——
每次 ``up`` 都从 ``STATE.json`` + ``.env`` 重新渲染，避免缓存与配置漂移。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

from Undefined.deploy.catalog import (
    COMPOSE_FILE_NAME,
    COMPOSE_PROJECT_NAME,
    DEPLOY_DIR_NAME,
    ENV_FILE_NAME,
    STATE_FILE_NAME,
)

#: 状态文件结构版本；不兼容变更时递增，旧文件会让 up 走“重新推导”而非报错。
STATE_SCHEMA_VERSION: Final[int] = 1

#: 含凭据的文件权限（仅 Unix 生效）。
SECRET_FILE_MODE: Final[int] = 0o600


def repo_root() -> Path:
    """定位仓库根目录。

    优先按包路径上溯（源码/开发安装），失败时从当前工作目录上溯，最后回退 cwd。
    ``deploy/`` 与 ``config.toml`` 都相对该目录。
    """
    package_root = Path(__file__).resolve().parent.parent.parent
    if (package_root / "pyproject.toml").is_file():
        return package_root

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return cwd


@dataclass(slots=True)
class DeployLayout:
    """``deploy/`` 下的固定路径。"""

    root: Path

    @classmethod
    def under(cls, repo: Path) -> "DeployLayout":
        return cls(root=(repo / DEPLOY_DIR_NAME).resolve())

    @property
    def state_file(self) -> Path:
        return self.root / STATE_FILE_NAME

    @property
    def env_file(self) -> Path:
        return self.root / ENV_FILE_NAME

    @property
    def compose_file(self) -> Path:
        return self.root / COMPOSE_FILE_NAME

    @property
    def backup_dir(self) -> Path:
        return self.root / "backup"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def searxng_dir(self) -> Path:
        return self.root / "searxng"

    @property
    def firecrawl_dir(self) -> Path:
        return self.root / "firecrawl"

    @property
    def lxmusic2api_dir(self) -> Path:
        return self.root / "lxmusic2api"

    @property
    def lxmusic2api_private_dir(self) -> Path:
        return self.lxmusic2api_dir / ".private"

    @property
    def napcat_dir(self) -> Path:
        return self.root / "napcat"

    @property
    def napcat_config_dir(self) -> Path:
        return self.napcat_dir / "config"

    @property
    def napcat_qq_dir(self) -> Path:
        return self.napcat_dir / "qq"

    def ensure(self) -> None:
        """创建全部运行态目录。"""
        for path in (
            self.root,
            self.backup_dir,
            self.data_dir,
            self.searxng_dir,
            self.firecrawl_dir,
            self.lxmusic2api_dir,
            self.lxmusic2api_private_dir,
            self.napcat_config_dir,
            self.napcat_qq_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class DeployState:
    """``STATE.json`` 的内存表示。"""

    services: tuple[str, ...] = ()
    mode: str = ""
    nagaagent: bool = False
    ports: dict[str, int] = field(default_factory=dict)
    generated_at: str = ""
    image_owner: str = ""
    schema_version: int = STATE_SCHEMA_VERSION
    project_name: str = COMPOSE_PROJECT_NAME

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_name": self.project_name,
            "mode": self.mode,
            "services": sorted(self.services),
            "nagaagent": self.nagaagent,
            "ports": {key: self.ports[key] for key in sorted(self.ports)},
            "image_owner": self.image_owner,
            "generated_at": self.generated_at or utc_timestamp(),
        }

    @classmethod
    def from_json(cls, data: Any) -> "DeployState | None":
        """解析状态文件；结构不可识别时返回 ``None``（调用方按首次部署处理）。"""
        if not isinstance(data, dict):
            return None
        if data.get("schema_version") != STATE_SCHEMA_VERSION:
            return None

        raw_services = data.get("services")
        services: tuple[str, ...] = ()
        if isinstance(raw_services, list):
            services = tuple(
                str(item) for item in raw_services if isinstance(item, str)
            )

        raw_ports = data.get("ports")
        ports: dict[str, int] = {}
        if isinstance(raw_ports, dict):
            for key, value in raw_ports.items():
                if isinstance(key, str) and isinstance(value, int):
                    ports[key] = value

        def _text(name: str) -> str:
            value = data.get(name)
            return value.strip() if isinstance(value, str) else ""

        return cls(
            services=services,
            mode=_text("mode"),
            nagaagent=bool(data.get("nagaagent")),
            ports=ports,
            generated_at=_text("generated_at"),
            image_owner=_text("image_owner"),
            project_name=_text("project_name") or COMPOSE_PROJECT_NAME,
        )


def utc_timestamp() -> str:
    """UTC ISO-8601 时间戳（秒精度），用于文件名与状态记录。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_stamp_compact() -> str:
    """文件名安全的 UTC 时间戳（不含冒号，跨平台可用）。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_text(path: Path, content: str, *, secret: bool = False) -> None:
    """原子写入文本，可选收紧权限。

    与运行时共用同一套写入语义（``utils/io.py`` 的原子替换 + ``utils/file_lock``
    的跨平台文件锁），避免部署脚本自己造一份 IO 实现。
    """
    from Undefined.utils.file_lock import FileLock

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with FileLock(lock_path, shared=False):
        _atomic_replace(path, content)
    if secret and os.name == "posix":
        path.chmod(SECRET_FILE_MODE)


def _atomic_replace(target: Path, content: str) -> None:
    """同目录临时文件 + ``os.replace``，保证读者不会看到半个文件。"""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def read_state(layout: DeployLayout) -> DeployState | None:
    """读取状态文件；缺失或不可识别时返回 ``None``。"""
    if not layout.state_file.is_file():
        return None
    try:
        data = json.loads(layout.state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return DeployState.from_json(data)


def save_state(layout: DeployLayout, state: DeployState) -> None:
    """写入状态文件（非敏感，普通权限）。"""
    state.generated_at = state.generated_at or utc_timestamp()
    payload = json.dumps(state.to_json(), indent=2, ensure_ascii=False) + "\n"
    write_text(layout.state_file, payload)


__all__ = [
    "DeployLayout",
    "DeployState",
    "SECRET_FILE_MODE",
    "STATE_SCHEMA_VERSION",
    "read_state",
    "repo_root",
    "save_state",
    "utc_stamp_compact",
    "utc_timestamp",
    "write_text",
]
