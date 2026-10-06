from __future__ import annotations

import importlib.util
import json
import subprocess
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


@pytest.fixture(autouse=True)
def _isolate_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("tests must not run external commands")

    monkeypatch.setattr(bump_version.subprocess, "run", forbidden)


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


def _assert_all_versions(root: Path, version: str) -> None:
    assert (
        tomllib_loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
        == version
    )
    assert f'__version__: str = "{version}"' in (
        root / "src" / "Undefined" / "__init__.py"
    ).read_text(encoding="utf-8")
    for app in bump_version.NATIVE_APPS:
        app_root = app.app_root(root)
        tauri_root = app.tauri_root(root)
        assert _json_version(app_root / "package.json") == version
        assert _package_lock_versions(app_root / "package-lock.json") == (
            version,
            version,
        )
        assert (
            tomllib_loads((tauri_root / "Cargo.toml").read_text(encoding="utf-8"))[
                "package"
            ]["version"]
            == version
        )
        assert _json_version(tauri_root / "tauri.conf.json") == version
        assert (
            _cargo_lock_root_version(tauri_root / "Cargo.lock", app.cargo_package)
            == version
        )


@pytest.mark.parametrize(
    "failed_path",
    ["src/Undefined/__init__.py", "apps/undefined-chat/package.json"],
)
def test_same_version_retry_finishes_all_targets_after_partial_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_path: str
) -> None:
    _write_bump_project(tmp_path)
    assert Path.cwd() == tmp_path
    original_write = bump_version._write_if_changed
    sync_calls: list[Path] = []
    monkeypatch.setattr(
        bump_version,
        "sync_lock_files",
        lambda root, *, dry_run: sync_calls.append(root),
    )

    def fail_write(path: Path, text: str, dry_run: bool) -> bool:
        assert path.resolve().is_relative_to(tmp_path)
        if path == tmp_path / failed_path:
            raise OSError("temporarily unavailable")
        result: bool = original_write(path, text, dry_run)
        return result

    monkeypatch.setattr(bump_version, "_write_if_changed", fail_write)
    with pytest.raises(OSError, match="temporarily unavailable"):
        bump_version.bump_project_versions(
            "2.0.0", project_root=tmp_path, dry_run=False
        )
    assert bump_version._read_current_version(tmp_path) == "2.0.0"
    assert not sync_calls
    monkeypatch.setattr(bump_version, "_write_if_changed", original_write)

    result = bump_version.bump_project_versions(
        "2.0.0", project_root=tmp_path, dry_run=False
    )

    assert result.old_version == result.new_version == "2.0.0"
    assert result.changed_paths
    assert sync_calls == [tmp_path]
    _assert_all_versions(tmp_path, "2.0.0")


def test_same_version_retry_reruns_all_lock_commands_after_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bump_project(tmp_path)
    calls: list[tuple[tuple[str, ...], Path]] = []
    fail_next_npm = True
    uv_runs = 0

    def run(
        command: list[str], *, cwd: Path, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal fail_next_npm, uv_runs
        assert cwd.resolve().is_relative_to(tmp_path)
        assert check
        calls.append((tuple(command), cwd))
        if command[0] == "npm" and fail_next_npm:
            fail_next_npm = False
            raise subprocess.CalledProcessError(1, command)
        if command[0] == "uv":
            uv_runs += 1
            (cwd / "uv.lock").write_text(f"sync_count={uv_runs}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bump_version.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        bump_version.bump_project_versions(
            "2.0.0", project_root=tmp_path, dry_run=False
        )
    _assert_all_versions(tmp_path, "2.0.0")
    calls.clear()

    result = bump_version.bump_project_versions(
        "2.0.0", project_root=tmp_path, dry_run=False
    )

    assert [command for command, _ in calls] == [
        ("uv", "sync"),
        ("npm", "install", "--package-lock-only"),
        ("cargo", "update", "--workspace"),
        ("npm", "install", "--package-lock-only"),
        ("cargo", "update", "--workspace"),
    ]
    assert result.changed_paths == ("uv.lock",)
    _assert_all_versions(tmp_path, "2.0.0")


def test_same_version_dry_run_detects_other_target_without_writing_or_syncing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_bump_project(tmp_path, version="2.0.0")
    target = tmp_path / "src" / "Undefined" / "__init__.py"
    target.write_text('__version__: str = "1.2.3"\n', encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    monkeypatch.setattr(
        bump_version,
        "sync_lock_files",
        lambda *args, **kwargs: pytest.fail("dry-run must not sync"),
    )

    result = bump_version.bump_project_versions(
        "2.0.0", project_root=tmp_path, dry_run=True
    )

    assert result.changed_paths == ("src/Undefined/__init__.py",)
    assert {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


def test_same_version_cli_reports_completed_lock_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_bump_project(tmp_path, version="2.0.0")
    sync_calls: list[Path] = []
    monkeypatch.setattr(bump_version, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        bump_version,
        "sync_lock_files",
        lambda root, *, dry_run: sync_calls.append(root),
    )

    assert bump_version.main(["2.0.0"]) == 0

    assert sync_calls == [tmp_path]
    output = capsys.readouterr().out
    assert "lock 文件同步完成" in output
    assert "无需更新" not in output
