#!/usr/bin/env python3
"""统一更新项目所有版本号。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from typing import Any, cast


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from release_apps import NATIVE_APPS, NativeApp  # noqa: E402


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[\w.]+)?(?:\+[\w.]+)?$")


@dataclass(frozen=True, slots=True)
class BumpResult:
    old_version: str
    new_version: str
    changed_paths: tuple[str, ...]


def _read_current_version(project_root: Path) -> str:
    """从 pyproject.toml 读取当前版本。"""
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise ValueError("无法从 pyproject.toml 读取当前版本")
    return match.group(1)


def _relative(project_root: Path, path: Path) -> str:
    return str(path.relative_to(project_root))


def _write_if_changed(path: Path, text: str, dry_run: bool) -> bool:
    old_text = path.read_text(encoding="utf-8")
    if old_text == text:
        return False
    if not dry_run:
        path.write_text(text, encoding="utf-8")
    return True


def _update_text_file(
    path: Path,
    pattern: str,
    replacement: str,
    dry_run: bool,
) -> bool:
    """用正则替换文本文件中的版本号，返回是否有变更。"""
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count == 0:
        raise ValueError(f"{path} 未匹配到版本模式")
    return _write_if_changed(path, new_text, dry_run)


def _update_json_version(path: Path, version: str, dry_run: bool) -> bool:
    data = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    old_version = data.get("version")
    if old_version == version:
        return False
    data["version"] = version
    text = json.dumps(data, ensure_ascii=False, indent="\t") + "\n"
    return _write_if_changed(path, text, dry_run)


def _update_package_lock(path: Path, version: str, dry_run: bool) -> bool:
    data = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise ValueError(f"{path} 缺少 packages")
    root_package = packages.get("")
    if not isinstance(root_package, dict):
        raise ValueError(f'{path} 缺少 packages[""]')

    changed = False
    if data.get("version") != version:
        data["version"] = version
        changed = True
    if root_package.get("version") != version:
        root_package["version"] = version
        changed = True
    if not changed:
        return False

    text = json.dumps(data, ensure_ascii=False, indent="\t") + "\n"
    return _write_if_changed(path, text, dry_run)


def _update_cargo_manifest(path: Path, version: str, dry_run: bool) -> bool:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    package = data.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("version"), str):
        raise ValueError(f"{path} 缺少 [package].version")
    return _update_text_file(
        path,
        r'^version\s*=\s*"[^"]+"',
        f'version = "{version}"',
        dry_run,
    )


def _update_cargo_lock_root_package(
    path: Path,
    package_name: str,
    version: str,
    dry_run: bool,
) -> bool:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list):
        raise ValueError(f"{path} 缺少 package 列表")
    if not any(
        isinstance(package, dict) and package.get("name") == package_name
        for package in packages
    ):
        raise ValueError(f"{path} 缺少 {package_name}")

    text = path.read_text(encoding="utf-8")
    package_pattern = re.compile(
        rf'(\[\[package\]\]\nname = "{re.escape(package_name)}"\nversion = )"[^"]+"',
        re.MULTILINE,
    )
    new_text, count = package_pattern.subn(rf'\g<1>"{version}"', text, count=1)
    if count == 0:
        raise ValueError(f"{path} 未匹配到 {package_name} 版本")
    return _write_if_changed(path, new_text, dry_run)


def _update_native_app_versions(
    project_root: Path,
    app: NativeApp,
    version: str,
    dry_run: bool,
) -> tuple[str, ...]:
    changed: list[str] = []
    app_root = app.app_root(project_root)
    tauri_root = app.tauri_root(project_root)
    package_json = app_root / "package.json"
    package_lock = app_root / "package-lock.json"
    cargo_toml = tauri_root / "Cargo.toml"
    tauri_conf = tauri_root / "tauri.conf.json"
    cargo_lock = tauri_root / "Cargo.lock"

    updates: tuple[tuple[Path, bool], ...] = (
        (
            package_json,
            _update_json_version(package_json, version, dry_run),
        ),
        (
            package_lock,
            _update_package_lock(package_lock, version, dry_run),
        ),
        (
            cargo_toml,
            _update_cargo_manifest(cargo_toml, version, dry_run),
        ),
        (
            tauri_conf,
            _update_json_version(tauri_conf, version, dry_run),
        ),
        (
            cargo_lock,
            _update_cargo_lock_root_package(
                cargo_lock,
                app.cargo_package,
                version,
                dry_run,
            ),
        ),
    )
    for path, did_change in updates:
        if did_change:
            changed.append(_relative(project_root, path))
    return tuple(changed)


def sync_lock_files(project_root: Path, *, dry_run: bool) -> None:
    """重新生成 lock 文件以同步依赖锁定内容。"""
    if dry_run:
        return

    print("\n同步 lock 文件...")

    print("  uv sync")
    subprocess.run(["uv", "sync"], cwd=project_root, check=True)

    for app in NATIVE_APPS:
        app_root = app.app_root(project_root)
        tauri_root = app.tauri_root(project_root)
        print(f"  npm install --package-lock-only ({app.app_dir})")
        subprocess.run(
            ["npm", "install", "--package-lock-only"],
            cwd=app_root,
            check=True,
        )
        print(f"  cargo update --workspace ({app.app_dir})")
        subprocess.run(["cargo", "update", "--workspace"], cwd=tauri_root, check=True)


def bump_project_versions(
    version: str,
    *,
    project_root: Path = _PROJECT_ROOT,
    dry_run: bool,
) -> BumpResult:
    root = project_root.resolve()
    if not _SEMVER_RE.match(version):
        raise ValueError(f"'{version}' 不是合法的语义版本号 (x.y.z)")

    current = _read_current_version(root)
    if version == current:
        return BumpResult(
            old_version=current,
            new_version=version,
            changed_paths=(),
        )

    changed: list[str] = []
    text_targets: tuple[tuple[Path, str, str], ...] = (
        (
            root / "pyproject.toml",
            r'^version\s*=\s*"[^"]+"',
            f'version = "{version}"',
        ),
        (
            root / "src" / "Undefined" / "__init__.py",
            r'^__version__\s*=\s*"[^"]+"',
            f'__version__ = "{version}"',
        ),
    )
    for path, pattern, replacement in text_targets:
        if _update_text_file(path, pattern, replacement, dry_run):
            changed.append(_relative(root, path))

    for app in NATIVE_APPS:
        changed.extend(_update_native_app_versions(root, app, version, dry_run))

    if changed and not dry_run:
        sync_lock_files(root, dry_run=False)

    return BumpResult(
        old_version=current,
        new_version=version,
        changed_paths=tuple(changed),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="统一更新项目版本号")
    parser.add_argument("version", help="新版本号，如 3.3.0")
    parser.add_argument("--dry-run", action="store_true", help="仅预览变更，不写入文件")
    parser.add_argument("--commit", action="store_true", help="更新后自动 git commit")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    new_version = cast(str, args.version)
    dry_run = cast(bool, args.dry_run)
    should_commit = cast(bool, args.commit)

    try:
        result = bump_project_versions(
            new_version,
            project_root=_PROJECT_ROOT,
            dry_run=dry_run,
        )
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if not result.changed_paths:
        print(f"版本已经是 {result.old_version}，无需更新")
        return 0

    prefix = "(dry-run) " if dry_run else ""
    print(f"{prefix}版本 {result.old_version} → {result.new_version}\n")
    for path in result.changed_paths:
        print(f"  ✓ {path}")

    if should_commit and not dry_run:
        print("\n创建 git commit...")
        subprocess.run(
            ["git", "add", *result.changed_paths, "uv.lock"],
            cwd=_PROJECT_ROOT,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"chore(version): bump version to {new_version}"],
            cwd=_PROJECT_ROOT,
            check=True,
        )
        print(f"\n完成! 已提交版本 {new_version}")
    elif not dry_run:
        print(f"\n完成! 版本已更新为 {new_version}")
        print("提示: 使用 --commit 可自动提交，或手动 git add + commit")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
