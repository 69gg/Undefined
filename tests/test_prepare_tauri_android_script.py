from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "prepare_tauri_android.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_tauri_android", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load prepare_tauri_android.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prepare_tauri_android = _load_script()


def _write_app(root: Path, *, name: str = "undefined-chat") -> Path:
    app_dir = root / "apps" / name
    tauri_dir = app_dir / "src-tauri"
    android_main = tauri_dir / "gen" / "android" / "app" / "src" / "main"
    package_dir = android_main / "java" / "com" / "undefined" / "chat"
    package_dir.mkdir(parents=True)
    (app_dir / "package.json").write_text(
        json.dumps({"name": name, "version": "1.0.0"}, indent="\t") + "\n",
        encoding="utf-8",
    )
    tauri_dir.mkdir(parents=True, exist_ok=True)
    (tauri_dir / "tauri.conf.json").write_text(
        json.dumps(
            {"identifier": "com.undefined.chat", "version": "1.0.0"},
            indent="\t",
        )
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "MainActivity.kt").write_text(
        "package com.undefined.chat\n\nclass MainActivity : TauriActivity()\n",
        encoding="utf-8",
    )
    (android_main / "AndroidManifest.xml").write_text(
        """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\">
    <application android:theme=\"@style/AppTheme\">
        <activity android:name=\".MainActivity\" android:exported=\"true\" />
    </application>
</manifest>
""",
        encoding="utf-8",
    )
    return app_dir


def test_prepare_tauri_android_adds_chat_android_native_files(tmp_path: Path) -> None:
    app_dir = _write_app(tmp_path)

    changed = prepare_tauri_android.prepare_tauri_android(app_dir)

    activity_path = (
        app_dir
        / "src-tauri"
        / "gen"
        / "android"
        / "app"
        / "src"
        / "main"
        / "java"
        / "com"
        / "undefined"
        / "chat"
        / "HtmlPreviewActivity.kt"
    )
    secret_plugin_path = activity_path.parent / "SecretPlugin.kt"
    manifest_path = (
        app_dir
        / "src-tauri"
        / "gen"
        / "android"
        / "app"
        / "src"
        / "main"
        / "AndroidManifest.xml"
    )
    assert set(changed) == {activity_path, secret_plugin_path, manifest_path}
    assert activity_path.read_text(encoding="utf-8") == (
        "package com.undefined.chat\n\nclass HtmlPreviewActivity : TauriActivity()\n"
    )
    secret_plugin = secret_plugin_path.read_text(encoding="utf-8")
    assert "class SecretPlugin" in secret_plugin
    assert "@InvokeArg" in secret_plugin
    assert "invoke.parseArgs(SecretPayload::class.java)" in secret_plugin
    assert "invoke.parseArgs(SetSecretPayload::class.java)" in secret_plugin
    assert "invoke.getString" not in secret_plugin
    assert ".commit()" in secret_plugin
    assert "AndroidKeyStore" in secret_plugin
    assert "AES/GCM/NoPadding" in secret_plugin
    manifest = manifest_path.read_text(encoding="utf-8")
    assert 'android:name="com.undefined.chat.HtmlPreviewActivity"' in manifest
    assert 'android:exported="false"' in manifest


def test_prepare_tauri_android_is_idempotent(tmp_path: Path) -> None:
    app_dir = _write_app(tmp_path)

    prepare_tauri_android.prepare_tauri_android(app_dir)

    assert prepare_tauri_android.prepare_tauri_android(app_dir) == []


def test_prepare_tauri_android_skips_non_chat_apps_without_android_gen(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "apps" / "undefined-console"
    app_dir.mkdir(parents=True)
    (app_dir / "package.json").write_text(
        json.dumps({"name": "undefined-console"}, indent="\t") + "\n",
        encoding="utf-8",
    )

    assert prepare_tauri_android.prepare_tauri_android(app_dir) == []


def test_prepare_tauri_android_check_reports_missing_patch(tmp_path: Path) -> None:
    app_dir = _write_app(tmp_path)

    changed = prepare_tauri_android.prepare_tauri_android(app_dir, dry_run=True)

    assert len(changed) == 3
    assert not changed[0].exists()


def test_prepare_tauri_android_requires_generated_android_project(
    tmp_path: Path,
) -> None:
    app_dir = tmp_path / "apps" / "undefined-chat"
    tauri_dir = app_dir / "src-tauri"
    tauri_dir.mkdir(parents=True)
    (app_dir / "package.json").write_text(
        json.dumps({"name": "undefined-chat"}, indent="\t") + "\n",
        encoding="utf-8",
    )
    (tauri_dir / "tauri.conf.json").write_text(
        json.dumps({"identifier": "com.undefined.chat"}, indent="\t") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="tauri:android:init"):
        prepare_tauri_android.prepare_tauri_android(app_dir)
