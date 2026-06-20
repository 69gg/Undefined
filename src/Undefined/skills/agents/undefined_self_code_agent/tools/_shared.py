from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ALLOWED_DIRECTORIES: tuple[str, ...] = (
    "src",
    "scripts",
    "tests",
    "res",
    "docs",
    "apps",
)
ALLOWED_ROOT_FILES: tuple[str, ...] = (
    "README.md",
    "CHANGELOG.md",
    "ARCHITECTURE.md",
    "config.toml.example",
)
PROJECT_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "src/Undefined",
    "config.toml.example",
)
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "target",
        "dist",
        "build",
        ".vite",
        "coverage",
    }
)
MAX_TEXT_BYTES = 1_500_000
DEFAULT_MAX_CHARS = 60_000
DEFAULT_LINE_LIMIT = 200
DEFAULT_MAX_RESULTS = 100
DEFAULT_MAX_MATCHES = 100
MAX_LINE_LEN = 500


@dataclass(frozen=True)
class ResolvedPath:
    repo_root: Path
    path: Path
    rel_path: str


def allowed_roots_text() -> str:
    """返回允许访问范围说明。"""

    dirs = ", ".join(f"{name}/" for name in ALLOWED_DIRECTORIES)
    files = ", ".join(ALLOWED_ROOT_FILES)
    return f"允许目录: {dirs}; 允许根文件: {files}"


def find_repo_root(context: dict[str, Any]) -> Path:
    """解析 Undefined 仓库根目录。"""

    raw_root = context.get("repo_root") or context.get("project_root")
    candidates: list[Path] = []
    if raw_root:
        candidates.append(Path(raw_root))
    candidates.append(Path.cwd())
    candidates.extend(Path.cwd().parents)
    current = Path(__file__).resolve()
    candidates.extend(current.parents)

    seen: set[Path] = set()
    for candidate in candidates:
        root = candidate.resolve()
        if root in seen:
            continue
        seen.add(root)
        if all((root / marker).exists() for marker in PROJECT_MARKERS):
            return root

    raise ValueError("无法定位 Undefined 仓库根目录")


def _normalize_rel_path(value: str | None) -> str:
    rel = str(value or "").strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.rstrip("/")


def _is_excluded_by_parts(path: Path, repo_root: Path) -> bool:
    try:
        parts = path.relative_to(repo_root).parts
    except ValueError:
        return True
    return any(part in EXCLUDED_DIR_NAMES or part.startswith(".") for part in parts)


def _is_allowed_relative(rel_path: str, *, allow_root: bool) -> bool:
    if rel_path in {"", "."}:
        return allow_root
    if rel_path in ALLOWED_ROOT_FILES:
        return True
    first = rel_path.split("/", 1)[0]
    return first in ALLOWED_DIRECTORIES


def is_allowed_path(path: Path, repo_root: Path, *, allow_root: bool = False) -> bool:
    """判断路径是否位于允许访问范围内。"""

    try:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False
    if _is_excluded_by_parts(path.resolve(), repo_root.resolve()):
        return False
    return _is_allowed_relative(rel, allow_root=allow_root)


def resolve_allowed_path(
    path_value: str | None,
    context: dict[str, Any],
    *,
    allow_root: bool = False,
) -> ResolvedPath:
    """解析并校验仓库相对路径。"""

    repo_root = find_repo_root(context)
    rel = _normalize_rel_path(path_value)
    target = (repo_root / rel).resolve() if rel else repo_root.resolve()

    try:
        rel_path = target.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise PermissionError(f"路径越界: {path_value}") from exc

    if rel_path == ".":
        rel_path = ""
    if not is_allowed_path(target, repo_root, allow_root=allow_root):
        raise PermissionError(f"路径不在允许范围内: {path_value or '.'}")

    return ResolvedPath(repo_root=repo_root, path=target, rel_path=rel_path)


def resolve_search_root(
    path_value: str | None,
    context: dict[str, Any],
) -> ResolvedPath:
    """解析搜索根路径，空路径表示整个允许范围。"""

    return resolve_allowed_path(path_value, context, allow_root=True)


def iter_allowed_files(repo_root: Path, root: Path | None = None) -> Iterable[Path]:
    """遍历允许范围内的文件。"""

    base = (root or repo_root).resolve()
    roots: list[Path]
    if base == repo_root.resolve():
        roots = [repo_root / name for name in ALLOWED_DIRECTORIES]
        roots.extend(repo_root / name for name in ALLOWED_ROOT_FILES)
    else:
        roots = [base]

    for item in roots:
        if not item.exists():
            continue
        if item.is_file():
            if is_allowed_path(item, repo_root):
                yield item
            continue
        if not item.is_dir() or not is_allowed_path(item, repo_root):
            continue
        for path in item.rglob("*"):
            if not path.is_file():
                continue
            if not is_allowed_path(path, repo_root):
                continue
            yield path


def is_probably_text(raw: bytes) -> bool:
    """粗略判断字节内容是否适合作为文本读取。"""

    if b"\x00" in raw:
        return False
    if not raw:
        return True
    control = sum(1 for value in raw if value < 32 and value not in {9, 10, 12, 13})
    return control <= max(12, len(raw) // 20)


def decode_text(raw: bytes) -> str:
    """按常见源码/文档编码解码文本。"""

    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text_file(path: Path) -> tuple[str, bool, int]:
    """读取文本文件，返回内容、是否因大小截断、原始字节数。"""

    size = path.stat().st_size
    with open(path, "rb") as file:
        raw = file.read(MAX_TEXT_BYTES + 1)
    truncated_bytes = len(raw) > MAX_TEXT_BYTES
    if truncated_bytes:
        raw = raw[:MAX_TEXT_BYTES]
    if not is_probably_text(raw):
        raise UnicodeError("文件看起来是二进制文件")
    return decode_text(raw), truncated_bytes, size


def clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """将任意输入规范为整数范围。"""

    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def format_relative(path: Path, repo_root: Path) -> str:
    """格式化为仓库相对路径。"""

    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def path_matches_include(path: Path, repo_root: Path, include: str) -> bool:
    """判断文件是否匹配 include glob。"""

    if not include:
        return True
    rel = format_relative(path, repo_root)
    return fnmatch.fnmatch(rel, include) or fnmatch.fnmatch(path.name, include)


def compile_pattern(
    pattern: str,
    *,
    is_regex: bool,
    case_sensitive: bool,
) -> re.Pattern[str]:
    """编译搜索模式。"""

    flags = 0 if case_sensitive else re.IGNORECASE
    source = pattern if is_regex else re.escape(pattern)
    return re.compile(source, flags)


def trim_line(line: str, max_len: int = MAX_LINE_LEN) -> str:
    """截断过长的单行输出。"""

    if len(line) <= max_len:
        return line
    return line[:max_len] + "..."
