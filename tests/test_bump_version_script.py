from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "bump_version.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_version_script", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load bump_version.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bump_version = _load_script()


def _write_bump_project(root: Path, *, version: str = "1.2.3") -> None:
    (root / "src" / "Undefined").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "Undefined-bot"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "Undefined" / "__init__.py").write_text(
        f'__version__: str = "{version}"\n',
        encoding="utf-8",
    )

    for app_dir, cargo_package in (
        ("undefined-console", "undefined_console"),
        ("undefined-chat", "undefined_chat"),
    ):
        app_root = root / "apps" / app_dir
        tauri_root = app_root / "src-tauri"
        tauri_root.mkdir(parents=True)
        (app_root / "package.json").write_text(
            json.dumps({"name": app_dir, "version": version}, indent="\t") + "\n",
            encoding="utf-8",
        )
        (app_root / "package-lock.json").write_text(
            json.dumps(
                {
                    "name": app_dir,
                    "version": version,
                    "packages": {"": {"name": app_dir, "version": version}},
                },
                indent="\t",
            )
            + "\n",
            encoding="utf-8",
        )
        (tauri_root / "Cargo.toml").write_text(
            f'[package]\nname = "{cargo_package}"\nversion = "{version}"\n',
            encoding="utf-8",
        )
        (tauri_root / "tauri.conf.json").write_text(
            (
                "{\n"
                f'\t"productName": "{app_dir}",\n'
                f'\t"version": "{version}",\n'
                '\t"bundle": {\n'
                '\t\t"targets": ["appimage", "deb", "dmg", "msi", "nsis"]\n'
                "\t}\n"
                "}\n"
            ),
            encoding="utf-8",
        )
        (tauri_root / "Cargo.lock").write_text(
            f'version = 3\n\n[[package]]\nname = "{cargo_package}"\nversion = "{version}"\n\n[[package]]\nname = "dependency"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )


def _json_version(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data["version"]
    if not isinstance(value, str):
        raise AssertionError(f"{path} version is not a string")
    return value


def _package_lock_versions(path: Path) -> tuple[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = data["version"]
    root_version = data["packages"][""]["version"]
    if not isinstance(version, str) or not isinstance(root_version, str):
        raise AssertionError(f"{path} package lock versions are not strings")
    return version, root_version


def _cargo_lock_root_version(path: Path, package_name: str) -> str:
    packages = tomllib_loads(path.read_text(encoding="utf-8"))["package"]
    if not isinstance(packages, list):
        raise AssertionError(f"{path} has no package list")
    for package in packages:
        if isinstance(package, dict) and package.get("name") == package_name:
            version = package.get("version")
            if not isinstance(version, str):
                raise AssertionError(f"{path} {package_name} version is not a string")
            return version
    raise AssertionError(f"{path} is missing {package_name}")


def tomllib_loads(text: str) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(text)


def test_bump_project_versions_updates_console_and_chat_manifests_and_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_bump_project(tmp_path)
    sync_calls: list[Path] = []
    monkeypatch.setattr(
        bump_version,
        "sync_lock_files",
        lambda project_root, *, dry_run: sync_calls.append(project_root),
    )

    result = bump_version.bump_project_versions(
        "2.0.0",
        project_root=tmp_path,
        dry_run=False,
    )

    assert set(result.changed_paths) == {
        "pyproject.toml",
        "src/Undefined/__init__.py",
        "apps/undefined-console/package.json",
        "apps/undefined-console/package-lock.json",
        "apps/undefined-console/src-tauri/Cargo.toml",
        "apps/undefined-console/src-tauri/tauri.conf.json",
        "apps/undefined-console/src-tauri/Cargo.lock",
        "apps/undefined-chat/package.json",
        "apps/undefined-chat/package-lock.json",
        "apps/undefined-chat/src-tauri/Cargo.toml",
        "apps/undefined-chat/src-tauri/tauri.conf.json",
        "apps/undefined-chat/src-tauri/Cargo.lock",
    }
    assert sync_calls == [tmp_path.resolve()]
    assert 'version = "2.0.0"' in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert '__version__: str = "2.0.0"' in (
        tmp_path / "src" / "Undefined" / "__init__.py"
    ).read_text(encoding="utf-8")

    for app_dir, cargo_package in (
        ("undefined-console", "undefined_console"),
        ("undefined-chat", "undefined_chat"),
    ):
        app_root = tmp_path / "apps" / app_dir
        tauri_root = app_root / "src-tauri"
        assert _json_version(app_root / "package.json") == "2.0.0"
        assert _package_lock_versions(app_root / "package-lock.json") == (
            "2.0.0",
            "2.0.0",
        )
        assert 'version = "2.0.0"' in (tauri_root / "Cargo.toml").read_text(
            encoding="utf-8"
        )
        assert _json_version(tauri_root / "tauri.conf.json") == "2.0.0"
        assert '\t\t"targets": ["appimage", "deb", "dmg", "msi", "nsis"]' in (
            tauri_root / "tauri.conf.json"
        ).read_text(encoding="utf-8")
        assert (
            _cargo_lock_root_version(tauri_root / "Cargo.lock", cargo_package)
            == "2.0.0"
        )


def test_bump_project_versions_dry_run_does_not_write_or_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_bump_project(tmp_path)
    monkeypatch.setattr(
        bump_version,
        "sync_lock_files",
        lambda project_root, *, dry_run: pytest.fail("dry-run should not sync locks"),
    )

    result = bump_version.bump_project_versions(
        "2.0.0",
        project_root=tmp_path,
        dry_run=True,
    )

    assert result.changed_paths
    assert 'version = "1.2.3"' in (tmp_path / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_bump_project_versions_rejects_invalid_version(tmp_path: Path) -> None:
    _write_bump_project(tmp_path)

    with pytest.raises(ValueError, match="不是合法的语义版本号"):
        bump_version.bump_project_versions(
            "2",
            project_root=tmp_path,
            dry_run=True,
        )
