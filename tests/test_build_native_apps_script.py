from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "build_native_apps.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_native_apps_script", _SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load build_native_apps.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_native_apps = _load_script()


def _write_app_tree(
    root: Path, app_dir: str, *, with_node_modules: bool = True
) -> None:
    app_root = root / "apps" / app_dir
    tauri_root = app_root / "src-tauri"
    tauri_root.mkdir(parents=True)
    (app_root / "package.json").write_text('{"scripts":{}}\n', encoding="utf-8")
    if with_node_modules:
        tauri_bin = app_root / "node_modules" / ".bin"
        tauri_bin.mkdir(parents=True)
        (tauri_bin / "tauri").write_text("", encoding="utf-8")


def _write_project(root: Path, *, with_node_modules: bool = True) -> None:
    _write_app_tree(root, "undefined-console", with_node_modules=with_node_modules)
    _write_app_tree(root, "undefined-chat", with_node_modules=with_node_modules)


def _options(
    *,
    product: str = "chat",
    targets: str = "android",
    android_abi: str = "arm64-v8a",
    desktop_bundles: str = "deb",
    output_dir: Path,
    dry_run: bool = False,
    no_install_deps: bool = False,
    android_init: str = "auto",
) -> object:
    return build_native_apps.BuildOptions(
        product=product,
        targets=targets,
        android_abi=android_abi,
        desktop_bundles=desktop_bundles,
        output_dir=output_dir,
        dry_run=dry_run,
        no_install_deps=no_install_deps,
        android_init=android_init,
    )


def test_selected_android_targets_supports_all() -> None:
    targets = build_native_apps.selected_android_targets("all")

    assert [target.abi_label for target in targets] == [
        "arm64-v8a",
        "armeabi-v7a",
        "x86",
        "x86_64",
    ]
    assert targets[0].tauri_target == "aarch64"
    assert targets[0].rust_target == "aarch64-linux-android"


def test_build_environment_sets_android_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/home/tester"))
    env = build_native_apps.build_environment(
        Path("/project"),
        env={"ANDROID_HOME": "/home/tester/Android/Sdk", "PATH": "/usr/bin"},
    )

    assert env["JAVA_HOME"] == "/usr/lib/jvm/java-17-openjdk"
    assert env["ANDROID_HOME"] == "/home/tester/Android/Sdk"
    assert env["ANDROID_SDK_ROOT"] == "/home/tester/Android/Sdk"
    assert env["NDK_HOME"] == "/home/tester/Android/Sdk/ndk/27.2.12479018"
    assert env["GRADLE_USER_HOME"] == "/home/tester/Android/Sdk/gradle"
    assert env["PATH"].startswith("/usr/lib/jvm/java-17-openjdk/bin")
    assert "/home/tester/Android/Sdk/cmdline-tools/latest/bin" in env["PATH"]
    if Path("/opt/android-sdk/cmdline-tools/latest/bin").exists():
        assert "/opt/android-sdk/cmdline-tools/latest/bin" in env["PATH"]
    assert env["PATH"].endswith("/usr/bin")


def test_make_build_tasks_android_chat_auto_initializes_and_checks(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    options = _options(output_dir=tmp_path / "out")

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.product == "chat"
    assert task.target_kind == "android"
    assert task.label == "arm64-v8a"
    assert [command.command for command in task.commands] == [
        ("npm", "run", "tauri:android:init"),
        ("npm", "run", "tauri:android:prepare:check"),
        (
            "npm",
            "run",
            "tauri:android:debug",
            "--",
            "--ci",
            "--apk",
            "--target",
            "aarch64",
        ),
    ]


def test_make_build_tasks_auto_skips_android_init_when_generated(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    (tmp_path / "apps" / "undefined-chat" / "src-tauri" / "gen" / "android").mkdir(
        parents=True
    )
    options = _options(output_dir=tmp_path / "out")

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert [command.command for command in tasks[0].commands] == [
        ("npm", "run", "tauri:android:prepare:check"),
        (
            "npm",
            "run",
            "tauri:android:debug",
            "--",
            "--ci",
            "--apk",
            "--target",
            "aarch64",
        ),
    ]


def test_make_build_tasks_includes_npm_ci_when_node_modules_missing(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, with_node_modules=False)
    options = _options(output_dir=tmp_path / "out")

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert tasks[0].commands[0].command == ("npm", "ci")


def test_make_build_tasks_respects_no_install_deps(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path, with_node_modules=False)
    options = _options(output_dir=tmp_path / "out", no_install_deps=True)

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert ("npm", "ci") not in [command.command for command in tasks[0].commands]


def test_make_build_tasks_all_products_and_abis(tmp_path: Path) -> None:
    _write_project(tmp_path)
    options = _options(
        product="all",
        android_abi="all",
        output_dir=tmp_path / "out",
    )

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert len(tasks) == 8
    assert {(task.product, task.label) for task in tasks} == {
        ("console", "arm64-v8a"),
        ("console", "armeabi-v7a"),
        ("console", "x86"),
        ("console", "x86_64"),
        ("chat", "arm64-v8a"),
        ("chat", "armeabi-v7a"),
        ("chat", "x86"),
        ("chat", "x86_64"),
    }
    console_init_count = sum(
        command.command == ("npm", "run", "tauri:android:init")
        for task in tasks
        if task.product == "console"
        for command in task.commands
    )
    chat_init_count = sum(
        command.command == ("npm", "run", "tauri:android:init")
        for task in tasks
        if task.product == "chat"
        for command in task.commands
    )
    chat_prepare_count = sum(
        command.command == ("npm", "run", "tauri:android:prepare:check")
        for task in tasks
        if task.product == "chat"
        for command in task.commands
    )
    assert console_init_count == 1
    assert chat_init_count == 1
    assert chat_prepare_count == 1


def test_make_build_tasks_desktop_linux_uses_no_strip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(build_native_apps, "_is_linux", lambda: True)
    options = _options(targets="desktop", output_dir=tmp_path / "out")

    tasks = build_native_apps.make_build_tasks(options, project_root=tmp_path)

    assert tasks[0].target_kind == "desktop"
    assert tasks[0].commands[-1].command == (
        "npm",
        "run",
        "tauri:build",
        "--",
        "--ci",
        "--bundles",
        "deb",
    )
    assert tasks[0].commands[-1].env["NO_STRIP"] == "true"


def test_make_build_tasks_desktop_rejects_non_linux(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    monkeypatch.setattr(build_native_apps, "_is_linux", lambda: False)
    options = _options(targets="desktop", output_dir=tmp_path / "out")

    with pytest.raises(RuntimeError, match="only supported on Linux"):
        build_native_apps.make_build_tasks(options, project_root=tmp_path)


def test_collect_artifacts_copies_matching_files(tmp_path: Path) -> None:
    _write_project(tmp_path)
    source_dir = tmp_path / "apps" / "undefined-chat" / "src-tauri" / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "app-arm64-debug.apk"
    source.write_text("apk", encoding="utf-8")
    unsigned = source_dir / "app-arm64-debug-unsigned.apk"
    unsigned.write_text("unsigned", encoding="utf-8")
    options = _options(output_dir=tmp_path / "out", android_init="skip")
    task = build_native_apps.make_build_tasks(options, project_root=tmp_path)[0]

    collected = build_native_apps.collect_artifacts(
        (task,),
        tmp_path / "out",
        dry_run=False,
    )

    assert len(collected) == 1
    assert collected[0].name == "Undefined-Chat-android-arm64-v8a-app-arm64-debug.apk"
    assert collected[0].read_text(encoding="utf-8") == "apk"


def test_collect_new_artifacts_only_copies_changed_files(tmp_path: Path) -> None:
    _write_project(tmp_path)
    source_dir = tmp_path / "apps" / "undefined-chat" / "src-tauri" / "target"
    source_dir.mkdir(parents=True, exist_ok=True)
    old_source = source_dir / "old.apk"
    old_source.write_text("old", encoding="utf-8")
    options = _options(output_dir=tmp_path / "out", android_init="skip")
    task = build_native_apps.make_build_tasks(options, project_root=tmp_path)[0]
    before = build_native_apps._artifact_snapshot(task)

    new_source = source_dir / "new.apk"
    new_source.write_text("new", encoding="utf-8")

    collected = build_native_apps.collect_new_artifacts(
        task,
        tmp_path / "out",
        before,
        dry_run=False,
    )

    assert [path.name for path in collected] == [
        "Undefined-Chat-android-arm64-v8a-new.apk"
    ]
    assert not (tmp_path / "out" / "Undefined-Chat-android-arm64-v8a-old.apk").exists()


def test_command_build_stops_when_check_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del tmp_path
    parser = build_native_apps.build_parser()
    args = parser.parse_args(["build", "--dry-run"])
    monkeypatch.setattr(
        build_native_apps,
        "check_environment",
        lambda *, targets, android_abi: (
            build_native_apps.CheckItem("rustup", False, "missing", "install rustup"),
        ),
    )
    monkeypatch.setattr(
        build_native_apps,
        "make_build_tasks",
        lambda options: pytest.fail("build should not continue after failed check"),
    )

    assert build_native_apps.command_build(args) == 1
