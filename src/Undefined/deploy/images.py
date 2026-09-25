"""镜像引用解析：本仓 GHCR 镜像、上游 pin 镜像、以及 Firecrawl 的资源上限。

所有会变的取值（仓库 owner、版本号、第三方 tag、上游 commit pin）都在这里集中
declare，部署脚本与 CI 共用同一份定义。
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# 本仓镜像（GHCR）
# --------------------------------------------------------------------------- #

GHCR_REGISTRY: Final[str] = "ghcr.io"
DEFAULT_IMAGE_OWNER: Final[str] = "69gg"
BOT_IMAGE_REPO: Final[str] = "undefined-bot"
LXMUSIC2API_IMAGE_REPO: Final[str] = "undefined-lxmusic2api"
DEV_VERSION: Final[str] = "dev"

# --------------------------------------------------------------------------- #
# 上游镜像 pin
#
# 全部固定到具体 tag，避免上游 latest 变动导致一次部署突然失败。
# 升级流程：改这里的常量 → 跑一次 CI 或本地验证 → 提交。
# ``playwright-service`` 与 ``nuq-postgres`` 上游不发布版本 tag，只能跟 latest。
# --------------------------------------------------------------------------- #

PIN_VERIFIED_ON: Final[str] = "2026-02-15"

NAPCAT_IMAGE: Final[str] = "mlikiowa/napcat-docker:v4.18.28"
SEARXNG_IMAGE: Final[str] = "docker.io/searxng/searxng:2026.9.25-d8ae3abd5"
FIRECRAWL_IMAGE: Final[str] = "ghcr.io/firecrawl/firecrawl:2.10.9"
FIRECRAWL_PLAYWRIGHT_IMAGE: Final[str] = "ghcr.io/firecrawl/playwright-service:latest"
FIRECRAWL_POSTGRES_IMAGE: Final[str] = "ghcr.io/firecrawl/nuq-postgres:latest"
FIRECRAWL_REDIS_IMAGE: Final[str] = "redis:alpine"
FIRECRAWL_RABBITMQ_IMAGE: Final[str] = "rabbitmq:3-management"

#: lxmusic2api 上游无 tag、无 release，只能锚定 commit；CI 用它 clone 并构建镜像。
LXMUSIC2API_UPSTREAM_REPO: Final[str] = "https://github.com/69gg/lxmusic2api.git"
#: 同一仓库的 ``owner/name`` 形式，供 actions/checkout 的 repository 参数使用。
LXMUSIC2API_UPSTREAM_SLUG: Final[str] = "69gg/lxmusic2api"
LXMUSIC2API_UPSTREAM_SHA: Final[str] = "a79c496836f9ce37ba7baf1331b2b01467373568"

#: Firecrawl 官方 compose 自带的资源上限（沿用其默认值，官方声明非最低要求）。
FIRECRAWL_API_CPUS: Final[str] = "4.0"
FIRECRAWL_API_MEMORY: Final[str] = "8G"
FIRECRAWL_PLAYWRIGHT_CPUS: Final[str] = "2.0"
FIRECRAWL_PLAYWRIGHT_MEMORY: Final[str] = "4G"


@dataclass(frozen=True, slots=True)
class ImageRef:
    """一个完整镜像引用（含 tag）。"""

    repository: str
    tag: str

    @property
    def reference(self) -> str:
        return f"{self.repository}:{self.tag}"


def resolve_image_owner(environ: dict[str, str] | None = None) -> str:
    """解析本仓镜像的 GHCR owner。

    优先读 CI 提供的环境变量，其次从仓库地址推导；两者都没有时回退到默认值，
    便于本地 clone 后直接 ``uv run deploy``。
    """
    env = os.environ if environ is None else environ
    owner = (
        env.get("UNDEFINED_DEPLOY_IMAGE_OWNER")
        or env.get("GITHUB_REPOSITORY_OWNER")
        or ""
    ).strip()
    if owner:
        return owner

    slug = (env.get("GITHUB_REPOSITORY") or "").strip()
    if "/" in slug:
        candidate = slug.split("/", 1)[0].strip()
        if candidate:
            return candidate
    return DEFAULT_IMAGE_OWNER


def resolve_project_version(repo_root: Path) -> str:
    """读取本仓版本号：先 ``pyproject.toml``，再已安装包元数据，最后 ``dev``。"""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        project = data.get("project")
        if isinstance(project, dict):
            version = project.get("version")
            if isinstance(version, str) and version.strip():
                return version.strip()

    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version

        try:
            return pkg_version("Undefined-bot").strip() or DEV_VERSION
        except PackageNotFoundError:
            return DEV_VERSION
    except Exception:  # pragma: no cover - importlib 元数据异常时不应中断部署
        return DEV_VERSION


def short_sha(sha: str, length: int = 7) -> str:
    """取短 sha 作为镜像 tag。"""
    cleaned = sha.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", cleaned):
        raise ValueError(f"lxmusic2api pin 必须是完整 commit sha，当前为 {sha!r}")
    return cleaned[:length].lower()


def bot_image(owner: str, version: str) -> ImageRef:
    """本体镜像引用。"""
    return ImageRef(f"{GHCR_REGISTRY}/{owner}/{BOT_IMAGE_REPO}", f"v{version}")


def lxmusic2api_image(owner: str, sha: str) -> ImageRef:
    """lxmusic2api 镜像引用（tag 为上游短 sha）。"""
    return ImageRef(f"{GHCR_REGISTRY}/{owner}/{LXMUSIC2API_IMAGE_REPO}", short_sha(sha))


def vendor_images() -> dict[str, str]:
    """服务 key -> 上游 pin 镜像引用，供生成器与测试共享。"""
    return {
        "napcat": NAPCAT_IMAGE,
        "searxng": SEARXNG_IMAGE,
        "firecrawl": FIRECRAWL_IMAGE,
        "firecrawl_playwright": FIRECRAWL_PLAYWRIGHT_IMAGE,
        "firecrawl_postgres": FIRECRAWL_POSTGRES_IMAGE,
        "firecrawl_redis": FIRECRAWL_REDIS_IMAGE,
        "firecrawl_rabbitmq": FIRECRAWL_RABBITMQ_IMAGE,
    }


__all__ = [
    "BOT_IMAGE_REPO",
    "DEFAULT_IMAGE_OWNER",
    "DEV_VERSION",
    "FIRECRAWL_API_CPUS",
    "FIRECRAWL_API_MEMORY",
    "FIRECRAWL_IMAGE",
    "FIRECRAWL_PLAYWRIGHT_CPUS",
    "FIRECRAWL_PLAYWRIGHT_IMAGE",
    "FIRECRAWL_PLAYWRIGHT_MEMORY",
    "FIRECRAWL_POSTGRES_IMAGE",
    "FIRECRAWL_RABBITMQ_IMAGE",
    "FIRECRAWL_REDIS_IMAGE",
    "GHCR_REGISTRY",
    "ImageRef",
    "LXMUSIC2API_IMAGE_REPO",
    "LXMUSIC2API_UPSTREAM_REPO",
    "LXMUSIC2API_UPSTREAM_SHA",
    "LXMUSIC2API_UPSTREAM_SLUG",
    "NAPCAT_IMAGE",
    "PIN_VERIFIED_ON",
    "SEARXNG_IMAGE",
    "bot_image",
    "lxmusic2api_image",
    "resolve_image_owner",
    "resolve_project_version",
    "short_sha",
    "vendor_images",
]
