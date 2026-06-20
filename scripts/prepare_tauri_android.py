"""Prepare generated Tauri Android projects for app-specific native code."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


CHAT_APP_NAME = "undefined-chat"
CHAT_PREVIEW_ACTIVITY = "HtmlPreviewActivity"
CHAT_SECRET_PLUGIN = "SecretPlugin"
MAIN_ACTIVITY_FILE = "MainActivity.kt"


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _app_name(app_dir: Path) -> str:
    package_json = app_dir / "package.json"
    data = _read_json_object(package_json)
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{package_json} is missing string field 'name'")
    return name


def _tauri_identifier(app_dir: Path) -> str:
    tauri_conf = app_dir / "src-tauri" / "tauri.conf.json"
    data = _read_json_object(tauri_conf)
    identifier = data.get("identifier")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"{tauri_conf} is missing string field 'identifier'")
    return identifier


def _android_root(app_dir: Path) -> Path:
    return app_dir / "src-tauri" / "gen" / "android"


def _find_android_manifest(android_root: Path) -> Path:
    candidates = sorted(android_root.glob("**/app/src/main/AndroidManifest.xml"))
    if not candidates:
        candidates = sorted(android_root.glob("**/AndroidManifest.xml"))
    if not candidates:
        raise FileNotFoundError(
            f"AndroidManifest.xml not found under {android_root}; "
            "run `npm run tauri:android:init` first"
        )
    return candidates[0]


def _package_from_kotlin_file(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*$", text)
    return match.group(1) if match else None


def _find_kotlin_package(android_root: Path, fallback: str) -> tuple[str, Path]:
    main_activity = sorted(android_root.glob(f"**/{MAIN_ACTIVITY_FILE}"))
    for path in main_activity:
        package_name = _package_from_kotlin_file(path)
        if package_name:
            return package_name, path.parent

    java_roots = sorted(android_root.glob("**/app/src/main/java"))
    if java_roots:
        package_dir = java_roots[0].joinpath(*fallback.split("."))
        return fallback, package_dir

    raise FileNotFoundError(
        f"Android Java/Kotlin source root not found under {android_root}; "
        "run `npm run tauri:android:init` first"
    )


def _activity_source(package_name: str) -> str:
    return (
        f"package {package_name}\n\nclass {CHAT_PREVIEW_ACTIVITY} : TauriActivity()\n"
    )


def _secret_plugin_source(package_name: str) -> str:
    return f"""package {package_name}

import android.app.Activity
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@InvokeArg
internal class SecretPayload {{
    lateinit var key: String
}}

@InvokeArg
internal class SetSecretPayload {{
    lateinit var key: String
    lateinit var value: String
}}

@TauriPlugin
class {CHAT_SECRET_PLUGIN}(private val activity: Activity) : Plugin(activity) {{
    private val prefs by lazy {{
        activity.getSharedPreferences("undefined_chat_secure_secrets", Context.MODE_PRIVATE)
    }}

    @Command
    fun isAvailable(invoke: Invoke) {{
        try {{
            ensureKey()
            val ret = JSObject()
            ret.put("available", true)
            invoke.resolve(ret)
        }} catch (error: Exception) {{
            invoke.reject("Android secure storage unavailable: ${{error.message}}")
        }}
    }}

    @Command
    fun getSecret(invoke: Invoke) {{
        val args = invoke.parseArgs(SecretPayload::class.java)
        if (args.key.isBlank()) {{
            invoke.reject("key is required")
            return
        }}
        try {{
            val stored = prefs.getString(args.key, null)
            val value = if (stored == null) null else decrypt(stored)
            val ret = JSObject()
            ret.put("value", value)
            invoke.resolve(ret)
        }} catch (error: Exception) {{
            invoke.reject("Android secure storage read failed: ${{error.message}}")
        }}
    }}

    @Command
    fun setSecret(invoke: Invoke) {{
        val args = invoke.parseArgs(SetSecretPayload::class.java)
        if (args.key.isBlank()) {{
            invoke.reject("key is required")
            return
        }}
        if (args.value.isBlank()) {{
            invoke.reject("value is required")
            return
        }}
        try {{
            if (!prefs.edit().putString(args.key, encrypt(args.value)).commit()) {{
                invoke.reject("Android secure storage write failed")
                return
            }}
            invoke.resolve(JSObject())
        }} catch (error: Exception) {{
            invoke.reject("Android secure storage write failed: ${{error.message}}")
        }}
    }}

    @Command
    fun deleteSecret(invoke: Invoke) {{
        val args = invoke.parseArgs(SecretPayload::class.java)
        if (args.key.isBlank()) {{
            invoke.reject("key is required")
            return
        }}
        if (!prefs.edit().remove(args.key).commit()) {{
            invoke.reject("Android secure storage delete failed")
            return
        }}
        invoke.resolve(JSObject())
    }}

    private fun ensureKey(): SecretKey {{
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply {{ load(null) }}
        keyStore.getKey(KEY_ALIAS, null)?.let {{ return it as SecretKey }}

        val keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore",
        )
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
        keyGenerator.init(spec)
        return keyGenerator.generateKey()
    }}

    private fun encrypt(value: String): String {{
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, ensureKey())
        val ciphertext = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return listOf(cipher.iv, ciphertext)
            .joinToString(":") {{ Base64.encodeToString(it, Base64.NO_WRAP) }}
    }}

    private fun decrypt(stored: String): String {{
        val parts = stored.split(":", limit = 2)
        require(parts.size == 2) {{ "invalid encrypted secret payload" }}
        val iv = Base64.decode(parts[0], Base64.NO_WRAP)
        val ciphertext = Base64.decode(parts[1], Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, ensureKey(), GCMParameterSpec(128, iv))
        return String(cipher.doFinal(ciphertext), Charsets.UTF_8)
    }}

    private companion object {{
        const val KEY_ALIAS = "undefined_chat_runtime_api_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }}
}}
"""


def _write_activity(package_dir: Path, package_name: str, dry_run: bool) -> Path | None:
    activity_path = package_dir / f"{CHAT_PREVIEW_ACTIVITY}.kt"
    expected = _activity_source(package_name)
    if activity_path.exists() and activity_path.read_text(encoding="utf-8") == expected:
        return None
    if not dry_run:
        package_dir.mkdir(parents=True, exist_ok=True)
        activity_path.write_text(expected, encoding="utf-8")
    return activity_path


def _write_secret_plugin(
    package_dir: Path, package_name: str, dry_run: bool
) -> Path | None:
    plugin_path = package_dir / f"{CHAT_SECRET_PLUGIN}.kt"
    expected = _secret_plugin_source(package_name)
    if plugin_path.exists() and plugin_path.read_text(encoding="utf-8") == expected:
        return None
    if not dry_run:
        package_dir.mkdir(parents=True, exist_ok=True)
        plugin_path.write_text(expected, encoding="utf-8")
    return plugin_path


def _activity_declared(manifest_text: str, package_name: str) -> bool:
    names = {
        f".{CHAT_PREVIEW_ACTIVITY}",
        f"{package_name}.{CHAT_PREVIEW_ACTIVITY}",
        CHAT_PREVIEW_ACTIVITY,
    }
    for name in names:
        if re.search(rf'android:name\s*=\s*"{re.escape(name)}"', manifest_text):
            return True
    return False


def _patch_manifest(
    manifest_path: Path, package_name: str, dry_run: bool
) -> Path | None:
    text = manifest_path.read_text(encoding="utf-8")
    if _activity_declared(text, package_name):
        return None
    activity = (
        "\n        <activity\n"
        f'            android:name="{package_name}.{CHAT_PREVIEW_ACTIVITY}"\n'
        '            android:exported="false" />\n'
    )
    marker = "</application>"
    if marker not in text:
        raise ValueError(f"{manifest_path} is missing an <application> block")
    patched = text.replace(marker, f"{activity}    {marker}", 1)
    if not dry_run:
        manifest_path.write_text(patched, encoding="utf-8")
    return manifest_path


def prepare_tauri_android(app_dir: Path, *, dry_run: bool = False) -> list[Path]:
    """Apply app-specific patches after `tauri android init`.

    Returns the paths that were changed, or would change in dry-run mode.
    """

    resolved_app_dir = app_dir.resolve()
    if _app_name(resolved_app_dir) != CHAT_APP_NAME:
        return []

    android_root = _android_root(resolved_app_dir)
    if not android_root.exists():
        raise FileNotFoundError(
            f"Android project not found under {android_root}; "
            "run `npm run tauri:android:init` first"
        )

    package_name, package_dir = _find_kotlin_package(
        android_root, _tauri_identifier(resolved_app_dir)
    )
    manifest_path = _find_android_manifest(android_root)
    changed: list[Path] = []
    activity_path = _write_activity(package_dir, package_name, dry_run)
    if activity_path is not None:
        changed.append(activity_path)
    secret_plugin_path = _write_secret_plugin(package_dir, package_name, dry_run)
    if secret_plugin_path is not None:
        changed.append(secret_plugin_path)
    patched_manifest = _patch_manifest(manifest_path, package_name, dry_run)
    if patched_manifest is not None:
        changed.append(patched_manifest)
    return changed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare generated Tauri Android projects."
    )
    parser.add_argument(
        "app_dir",
        type=Path,
        help="Native app directory, for example apps/undefined-chat or .",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generated Android patches are missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    changed = prepare_tauri_android(args.app_dir, dry_run=args.check)
    if args.check and changed:
        print("Generated Android project is missing required patches:")
        for path in changed:
            print(path)
        return 1
    for path in changed:
        print(f"prepared {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
