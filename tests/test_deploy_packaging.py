"""部署模板的打包与容器资源契约测试。

两件事分开验证：

1. 模板文件必须存在、非空，并且 ``.dockerignore`` 不会把它们排除掉——
   这是**无构建**的快速检查，每次跑测试都会执行。
2. wheel 里确实带上了模板——需要真的执行 ``uv build``，因此由环境变量
   ``UNDEFINED_DEPLOY_WHEEL_CHECK=1`` 门控（CI 里开启，本地默认跳过）。
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from Undefined.deploy import catalog, generate

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = Path(generate.__file__).resolve().parent / "templates"

#: 所有必须随包分发的模板文件。
REQUIRED_TEMPLATES = (
    "Dockerfile.bot",
    ".dockerignore",
    "compose.base.yaml",
    "compose.bot.yaml",
    "compose.napcat.yaml",
    "compose.searxng.yaml",
    "compose.firecrawl.yaml",
    "compose.lxmusic2api.yaml",
    "searxng.settings.yml",
    "lxmusic2api.config.toml",
)

#: ``.dockerignore`` 里必须出现的排除项（防止有人把 62M 的 dist/ 打进上下文）。
REQUIRED_DOCKERIGNORE_ENTRIES = (
    ".git",
    ".venv",
    "data",
    "dist",
    "code",
    "config.toml",
)


def _dockerignore_entries(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.rstrip("/"))
    return entries


def test_repo_dockerignore_excludes_heavy_paths() -> None:
    """构建上下文必须排除 .venv / dist / data 这些大体量目录。"""
    entries = _dockerignore_entries(REPO_ROOT / ".dockerignore")
    assert entries, "仓库根缺少 .dockerignore"
    missing = [item for item in REQUIRED_DOCKERIGNORE_ENTRIES if item not in entries]
    assert not missing, f".dockerignore 缺少排除项：{missing}"


def test_template_dockerignore_excludes_heavy_paths() -> None:
    entries = _dockerignore_entries(TEMPLATE_DIR / ".dockerignore")
    assert entries, "模板目录缺少 .dockerignore"
    missing = [item for item in REQUIRED_DOCKERIGNORE_ENTRIES if item not in entries]
    assert not missing, f"模板 .dockerignore 缺少排除项：{missing}"


def test_dockerignore_does_not_exclude_sources() -> None:
    """排除规则不能把镜像需要的源码/资源挡掉。"""
    entries = _dockerignore_entries(REPO_ROOT / ".dockerignore")
    for required in ("src", "res", "img", "config", "uv.lock", "pyproject.toml"):
        assert required not in entries, f".dockerignore 不应排除 {required}"


@pytest.mark.parametrize("name", REQUIRED_TEMPLATES)
def test_required_template_exists_and_is_not_empty(name: str) -> None:
    path = TEMPLATE_DIR / name
    assert path.is_file(), f"缺少模板 {name}"
    assert path.read_text(encoding="utf-8").strip(), f"模板 {name} 为空"


def test_every_service_fragment_is_declared_in_required_templates() -> None:
    for service in (*catalog.REQUIRED_SERVICES, *catalog.OPTIONAL_SERVICES):
        assert service.compose_fragment in REQUIRED_TEMPLATES, (
            f"{service.key} 的模板 {service.compose_fragment} 未纳入打包校验清单"
        )


def test_dockerfile_builds_from_repo_context() -> None:
    """Dockerfile 依赖的文件必须真的在仓库里（COPY 写错会在 CI 才炸）。"""
    text = (TEMPLATE_DIR / "Dockerfile.bot").read_text(encoding="utf-8")
    for source in (
        "pyproject.toml",
        "uv.lock",
        "README.md",
        "src",
        "res",
        "img",
        "config",
        "config.toml.example",
    ):
        assert f" {source}" in text or f"/{source}" in text, (
            f"Dockerfile 未引用 {source}"
        )
        assert (REPO_ROOT / source).exists(), f"仓库缺少 {source}"


def test_dockerfile_installs_runtime_dependencies() -> None:
    """ffmpeg / docker CLI / playwright 缺一不可，做成断言防止被误删。"""
    text = (TEMPLATE_DIR / "Dockerfile.bot").read_text(encoding="utf-8")
    assert "ffmpeg" in text
    assert "docker:27-cli" in text
    assert "playwright install" in text


@pytest.mark.skipif(
    os.environ.get("UNDEFINED_DEPLOY_WHEEL_CHECK") != "1",
    reason="需要真实构建 wheel，设置 UNDEFINED_DEPLOY_WHEEL_CHECK=1 后启用",
)
def test_wheel_contains_deploy_templates(tmp_path: Path) -> None:
    """CI 专用：确认模板随 wheel 分发（pip 安装的包也能用 deploy）。"""
    out_dir = tmp_path / "dist"
    completed = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    wheels = sorted(out_dir.glob("*.whl"))
    assert wheels, "未生成 wheel"

    with zipfile.ZipFile(wheels[-1]) as archive:
        names = set(archive.namelist())
        missing = [
            f"Undefined/deploy/templates/{name}"
            for name in REQUIRED_TEMPLATES
            if f"Undefined/deploy/templates/{name}" not in names
        ]
        assert not missing, f"wheel 缺少模板：{missing}"
        assert "Undefined/deploy/cli.py" in names
