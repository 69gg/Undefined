"""部署模板的打包与容器资源契约测试。

两件事分开验证：

1. 模板文件必须存在、非空，并且 ``.dockerignore`` 不会把它们排除掉——
   这是**无构建**的快速检查，每次跑测试都会执行。
2. wheel 里确实带上了模板——需要真的执行 ``uv build``，因此由环境变量
   ``UNDEFINED_DEPLOY_WHEEL_CHECK=1`` 门控（CI 里开启，本地默认跳过）。
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import tomllib
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


def _dockerfile_copy_sources() -> set[str]:
    """Dockerfile 里从构建上下文 COPY 的源路径。

    跳过 ``--from=`` 的跨阶段拷贝（那是镜像内路径，不是仓库文件）与含变量的行。
    """
    dockerfile = (TEMPLATE_DIR / "Dockerfile.bot").read_text(encoding="utf-8")
    copied: set[str] = set()
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if not stripped.startswith("COPY ") or "--from=" in stripped:
            continue
        parts = [token for token in stripped.split()[1:] if not token.startswith("--")]
        # 最后一个参数是目标路径，其余是源
        for source in parts[:-1]:
            if "$" in source:
                continue
            copied.add(source.rstrip("/"))
    return copied


def _dockerignore_rules(path: Path) -> list[tuple[str, bool]]:
    """按出现顺序给出 ``(pattern, is_negation)``（去注释与空行）。"""
    rules: list[tuple[str, bool]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            rules.append((line[1:].strip().rstrip("/"), True))
        else:
            rules.append((line.rstrip("/"), False))
    return rules


def _ignore_pattern_matches(pattern: str, source: str) -> bool:
    """Docker 的 .dockerignore 匹配语义（只覆盖本仓库用到的形态）。

    关键一条：不含 ``/`` 的模式按**任意层级**匹配，所以 ``*.md`` 会连仓库根的
    ``README.md`` / ``CHANGELOG.md`` 一起排掉，必须靠后面的 ``!`` 逐条放行。
    """
    if not pattern:
        return False
    parts = Path(source).parts
    if pattern.startswith("**/"):
        tail = pattern[3:]
        return fnmatch.fnmatchcase(source, tail) or any(
            fnmatch.fnmatchcase(part, tail) for part in parts
        )
    if "/" in pattern:
        return fnmatch.fnmatchcase(source, pattern)
    return fnmatch.fnmatchcase(Path(source).name, pattern) or any(
        fnmatch.fnmatchcase(part, pattern) for part in parts
    )


def _dockerignore_keeps(rules: list[tuple[str, bool]], source: str) -> bool:
    """按「后匹配者胜」判断 ``source`` 是否还留在构建上下文里。"""
    kept = True
    for pattern, negation in rules:
        if _ignore_pattern_matches(pattern, source):
            kept = negation
    return kept


def test_dockerfile_copy_sources_survive_dockerignore() -> None:
    """Dockerfile 里 COPY 的源路径必须真的留在构建上下文里。

    ``*.md`` 这类通配会把 ``README.md`` / ``CHANGELOG.md`` 一起排掉，只能靠后面
    的 ``!`` 放行——而旧断言写的是 ``source not in entries``（只比字面条目），对
    通配模式**恒真**：先漏了 README.md，2026-09 又漏了 CHANGELOG.md（v3.17.0 的
    release 因此在 ``uv sync`` 上炸掉）。这里按后匹配者胜真正求值一次。
    """
    copied = _dockerfile_copy_sources()
    assert copied, "未从 Dockerfile 解析出任何 COPY 源，测试需要更新"

    for ignore_file in (REPO_ROOT / ".dockerignore", TEMPLATE_DIR / ".dockerignore"):
        rules = _dockerignore_rules(ignore_file)
        assert rules, f"{ignore_file} 里没有有效规则"
        blocked = [
            item for item in sorted(copied) if not _dockerignore_keeps(rules, item)
        ]
        assert not blocked, (
            f"{ignore_file} 会把 Dockerfile COPY 的源挡在构建上下文外：{blocked}"
            "（通配排除后需要一条 ! 放行）"
        )


def _hatch_forced_includes() -> set[str]:
    """``[tool.hatch.build.targets.wheel.force-include]`` 的源路径（构建必需）。"""
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    return set(config.get("force-include") or {})


def test_dockerfile_copies_hatch_forced_includes() -> None:
    """镜像必须 COPY 上构建后端「强制包含」的源文件。

    force-include 的文件在 editable 构建（镜像里的 ``uv sync``）时**必须存在**，
    否则 hatchling 直接抛 ``FileNotFoundError: Forced include not found``，整条镜像
    构建失败。镜像只在 tag 上构建，所以这类缺失 PR 的 CI 完全看不到——v3.17.0 的
    release 就是死在 ``/app/CHANGELOG.md`` 上，连带动摇了 Release 资产与 PyPI 发布。
    """
    forced = _hatch_forced_includes()
    assert forced, "pyproject 里没有 force-include，本用例需要更新"
    copied = _dockerfile_copy_sources()

    for source in sorted(forced):
        assert (REPO_ROOT / source).is_file(), (
            f"force-include 的源在仓库里不存在：{source}"
        )
        covered = [
            item for item in copied if source == item or source.startswith(item + "/")
        ]
        assert covered, (
            f"Dockerfile.bot 没有 COPY {source}（force-include 的源），"
            f"镜像里的 uv sync 会因 Forced include not found 失败；"
            f"当前 COPY 源：{sorted(copied)}"
        )


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
    """Dockerfile 依赖的文件必须真的在仓库里（COPY 写错会在 CI 才炸）。

    旧写法是逐个 ``assert f" {source}" in text``：原文子串匹配既会漏（换个写法
    就匹配不到），也会被注释里的同名字符串骗过。这里直接解析 COPY 指令，断言
    每个源路径存在，并锁定几个必须在镜像里的关键文件。
    """
    sources = _dockerfile_copy_sources()
    assert sources, "未从 Dockerfile 解析出任何 COPY 源"

    for source in sorted(sources):
        assert (REPO_ROOT / source).exists(), (
            f"Dockerfile COPY 了仓库里不存在的路径：{source}"
        )

    required = {"pyproject.toml", "uv.lock", "src", "res", "config.toml.example"}
    assert required <= sources, f"镜像缺少关键文件：{sorted(required - sources)}"


def _docker_daemon_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


@pytest.mark.skipif(not _docker_daemon_available(), reason="需要可用的 Docker daemon")
def test_dockerfile_passes_buildkit_check() -> None:
    """用 BuildKit 的 ``--check`` 静态校验 Dockerfile。

    这里能真正验到「COPY 的源路径是否存在」「指令是否合法」，
    run 阶段不会执行、也不会拉镜像。
    """
    completed = subprocess.run(
        [
            "docker",
            "build",
            "--check",
            "--file",
            str(TEMPLATE_DIR / "Dockerfile.bot"),
            ".",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_gitignore_ignores_runtime_dir_without_touching_templates() -> None:
    """``deploy/`` 必须锚定到仓库根。

    不加前导 ``/`` 时该模式会匹配任意层级的同名目录，把
    ``src/Undefined/deploy``（模板与代码所在处）一起忽略掉。
    """
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "/deploy/" in patterns, ".gitignore 需要用 /deploy/ 锚定仓库根的运行态目录"
    assert "deploy/" not in patterns, (
        "未锚定的 deploy/ 会连 src/Undefined/deploy 一起忽略，请改用 /deploy/"
    )


def test_template_dir_is_not_ignored_by_any_pattern() -> None:
    """模板目录必须始终可被 git 跟踪（防止上面的坑以别的形式回归）。"""
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("src/Undefined/deploy")
    ]
    assert not offending, f".gitignore 不应忽略模板目录：{offending}"


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
