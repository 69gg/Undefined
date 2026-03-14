#!/usr/bin/env python3
"""统一更新项目所有版本号。

用法:
    uv run python scripts/bump_version.py 3.3.0
    uv run python scripts/bump_version.py 3.3.0 --dry-run
    uv run python scripts/bump_version.py 3.3.0 --commit
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 所有需要更新版本号的源文件及其匹配模式、替换模板
_VERSION_TARGETS: list[tuple[Path, str, str]] = [
    (
        _PROJECT_ROOT / "pyproject.toml",
        r'^version\s*=\s*"[^"]+"',
        'version = "{version}"',
    ),
    (
        _PROJECT_ROOT / "src" / "Undefined" / "__init__.py",
        r'^__version__\s*=\s*"[^"]+"',
        '__version__ = "{version}"',
    ),
    (
        _PROJECT_ROOT / "apps" / "undefined-console" / "src-tauri" / "Cargo.toml",
        r'^version\s*=\s*"[^"]+"',
        'version = "{version}"',
    ),
]

# JSON 文件中的版本字段（顶层 "version" key）
_JSON_TARGETS: list[Path] = [
    _PROJECT_ROOT / "apps" / "undefined-console" / "package.json",
    _PROJECT_ROOT / "apps" / "undefined-console" / "src-tauri" / "tauri.conf.json",
]

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?(?:\+[\w.]+)?$")


def _read_current_version() -> str:
    """从 pyproject.toml 读取当前版本。"""
    text = (_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        print("错误: 无法从 pyproject.toml 读取当前版本", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def _update_text_file(
    path: Path, pattern: str, replacement: str, dry_run: bool
) -> bool:
    """用正则替换文本文件中的版本号，返回是否有变更。"""
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count == 0:
        print(
            f"  警告: {path.relative_to(_PROJECT_ROOT)} 未匹配到版本模式",
            file=sys.stderr,
        )
        return False
    if text == new_text:
        return False
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def _update_json_file(path: Path, version: str, dry_run: bool) -> bool:
    """更新 JSON 文件中顶层 "version" 字段（正则替换，保留原始格式）。"""
    pattern = r'^(\s*"version"\s*:\s*)"[^"]+"'
    replacement = rf'\g<1>"{version}"'
    return _update_text_file(path, pattern, replacement, dry_run)


def _sync_lock_files(dry_run: bool) -> None:
    """重新生成 lock 文件以同步版本号。"""
    if dry_run:
        print("\n(dry-run) 将执行以下命令同步 lock 文件:")
        print("  uv sync")
        print("  npm install --package-lock-only  (in apps/undefined-console/)")
        print(
            "  cargo update --workspace         (in apps/undefined-console/src-tauri/)"
        )
        return

    print("\n同步 lock 文件...")

    print("  uv sync")
    subprocess.run(["uv", "sync"], cwd=_PROJECT_ROOT, check=True)

    console_dir = _PROJECT_ROOT / "apps" / "undefined-console"
    print("  npm install --package-lock-only")
    subprocess.run(
        ["npm", "install", "--package-lock-only"], cwd=console_dir, check=True
    )

    tauri_dir = console_dir / "src-tauri"
    print("  cargo update --workspace")
    subprocess.run(["cargo", "update", "--workspace"], cwd=tauri_dir, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="统一更新项目版本号")
    parser.add_argument("version", help="新版本号，如 3.3.0")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更，不写入文件")
    parser.add_argument("--commit", action="store_true", help="更新后自动 git commit")
    args = parser.parse_args()

    new_version: str = args.version
    if not _SEMVER_RE.match(new_version):
        print(f"错误: '{new_version}' 不是合法的语义版本号 (x.y.z)", file=sys.stderr)
        sys.exit(1)

    current = _read_current_version()
    if new_version == current:
        print(f"版本已经是 {current}，无需更新")
        return

    prefix = "(dry-run) " if args.dry_run else ""
    print(f"{prefix}版本 {current} → {new_version}\n")

    changed: list[str] = []

    # 文本文件
    for path, pattern, template in _VERSION_TARGETS:
        rel = str(path.relative_to(_PROJECT_ROOT))
        replacement = template.format(version=new_version)
        if _update_text_file(path, pattern, replacement, args.dry_run):
            print(f"  ✓ {rel}")
            changed.append(rel)
        else:
            print(f"  - {rel} (无变更)")

    # JSON 文件
    for path in _JSON_TARGETS:
        rel = str(path.relative_to(_PROJECT_ROOT))
        if _update_json_file(path, new_version, args.dry_run):
            print(f"  ✓ {rel}")
            changed.append(rel)
        else:
            print(f"  - {rel} (无变更)")

    if not changed:
        print("\n所有文件已是目标版本，无需更新")
        return

    _sync_lock_files(args.dry_run)

    if args.commit and not args.dry_run:
        print("\n创建 git commit...")
        lock_files = [
            "uv.lock",
            "apps/undefined-console/package-lock.json",
            "apps/undefined-console/src-tauri/Cargo.lock",
        ]
        subprocess.run(
            ["git", "add", *changed, *lock_files], cwd=_PROJECT_ROOT, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", f"chore(version): bump version to {new_version}"],
            cwd=_PROJECT_ROOT,
            check=True,
        )
        print(f"\n完成! 已提交版本 {new_version}")
    elif not args.dry_run:
        print(f"\n完成! 版本已更新为 {new_version}")
        print("提示: 使用 --commit 可自动提交，或手动 git add + commit")


if __name__ == "__main__":
    main()
