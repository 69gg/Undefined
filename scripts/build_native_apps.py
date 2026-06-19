#!/usr/bin/env python3
"""Build local native app artifacts for Undefined Console and Chat."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from release_apps import NATIVE_APPS, NativeApp  # noqa: E402


ANDROID_NDK_VERSION = "27.2.12479018"
ANDROID_PLATFORM_PACKAGE = "platforms;android-34"
ANDROID_BUILD_TOOLS_PACKAGE = "build-tools;34.0.0"
ANDROID_REQUIRED_PACKAGES = (
    "platform-tools",
    ANDROID_PLATFORM_PACKAGE,
    ANDROID_BUILD_TOOLS_PACKAGE,
    f"ndk;{ANDROID_NDK_VERSION}",
)

PRODUCT_CHOICES = ("chat", "console", "all")
TARGET_CHOICES = ("desktop", "android", "all")
ANDROID_ABI_CHOICES = ("arm64-v8a", "armeabi-v7a", "x86", "x86_64", "all")
ANDROID_INIT_CHOICES = ("auto", "always", "skip")
DESKTOP_BUNDLE_CHOICES = ("deb", "appimage", "all")


@dataclass(frozen=True, slots=True)
class AndroidTarget:
    abi_label: str
    tauri_target: str
    rust_target: str


@dataclass(frozen=True, slots=True)
class BuildCommand:
    description: str
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]


@dataclass(frozen=True, slots=True)
class BuildTask:
    product: str
    target_kind: str
    label: str
    app: NativeApp
    commands: tuple[BuildCommand, ...]
    artifact_patterns: tuple[str, ...]
    artifact_search_root: Path


@dataclass(frozen=True, slots=True)
class CheckItem:
    name: str
    ok: bool
    detail: str
    fix_hint: str | None = None


@dataclass(frozen=True, slots=True)
class BuildOptions:
    product: str
    targets: str
    android_abi: str
    desktop_bundles: str
    output_dir: Path
    dry_run: bool
    no_install_deps: bool
    android_init: str


ANDROID_TARGETS: tuple[AndroidTarget, ...] = (
    AndroidTarget("arm64-v8a", "aarch64", "aarch64-linux-android"),
    AndroidTarget("armeabi-v7a", "armv7", "armv7-linux-androideabi"),
    AndroidTarget("x86", "i686", "i686-linux-android"),
    AndroidTarget("x86_64", "x86_64", "x86_64-linux-android"),
)


def _app_product(app: NativeApp) -> str:
    return app.app_dir.removeprefix("undefined-")


def selected_apps(product: str) -> tuple[NativeApp, ...]:
    if product == "all":
        return NATIVE_APPS
    apps = tuple(app for app in NATIVE_APPS if _app_product(app) == product)
    if not apps:
        raise ValueError(f"Unknown product: {product}")
    return apps


def selected_android_targets(android_abi: str) -> tuple[AndroidTarget, ...]:
    if android_abi == "all":
        return ANDROID_TARGETS
    targets = tuple(
        target for target in ANDROID_TARGETS if target.abi_label == android_abi
    )
    if not targets:
        raise ValueError(f"Unknown Android ABI: {android_abi}")
    return targets


def selected_target_kinds(targets: str) -> tuple[str, ...]:
    if targets == "all":
        return ("desktop", "android")
    if targets not in ("desktop", "android"):
        raise ValueError(f"Unknown target kind: {targets}")
    return (targets,)


def _is_linux() -> bool:
    return platform.system().lower() == "linux"


def desktop_bundle_arg(desktop_bundles: str) -> str:
    if desktop_bundles == "all":
        return "appimage,deb"
    return desktop_bundles


def android_home(env: dict[str, str] | None = None) -> Path:
    current_env = os.environ if env is None else env
    value = current_env.get("ANDROID_HOME") or current_env.get("ANDROID_SDK_ROOT")
    if value:
        return Path(value).expanduser()
    opt_sdk = Path("/opt/android-sdk")
    if opt_sdk.exists():
        return opt_sdk
    return Path.home() / "Android" / "Sdk"


def build_environment(
    project_root: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    del project_root
    base = dict(os.environ if env is None else env)
    sdk_root = android_home(base)
    java_home = base.get("JAVA_HOME") or "/usr/lib/jvm/java-17-openjdk"
    build_tools = sdk_root / "build-tools" / "34.0.0"
    cmdline_tools = sdk_root / "cmdline-tools" / "latest" / "bin"
    system_cmdline_tools = Path("/opt/android-sdk/cmdline-tools/latest/bin")
    platform_tools = sdk_root / "platform-tools"
    ndk_home = Path(base.get("NDK_HOME", sdk_root / "ndk" / ANDROID_NDK_VERSION))
    java_bin = Path(java_home) / "bin"
    path_parts = (
        str(java_bin),
        str(cmdline_tools),
        str(system_cmdline_tools) if system_cmdline_tools.exists() else "",
        str(platform_tools),
        str(build_tools),
        base.get("PATH", ""),
    )
    base.update(
        {
            "JAVA_HOME": java_home,
            "ANDROID_HOME": str(sdk_root),
            "ANDROID_SDK_ROOT": str(sdk_root),
            "NDK_HOME": str(ndk_home),
            "GRADLE_USER_HOME": base.get("GRADLE_USER_HOME", str(sdk_root / "gradle")),
            "PATH": os.pathsep.join(part for part in path_parts if part),
        }
    )
    return base


def _npm_command(script: str, extra_args: Iterable[str] = ()) -> tuple[str, ...]:
    args = ("npm", "run", script)
    extra = tuple(extra_args)
    if extra:
        return (*args, "--", *extra)
    return args


def _needs_npm_ci(app: NativeApp, project_root: Path, no_install_deps: bool) -> bool:
    if no_install_deps:
        return False
    return not (app.app_root(project_root) / "node_modules" / ".bin" / "tauri").exists()


def _android_gen_exists(app: NativeApp, project_root: Path) -> bool:
    return (app.tauri_root(project_root) / "gen" / "android").exists()


def _android_init_commands(
    app: NativeApp,
    project_root: Path,
    env: dict[str, str],
    android_init: str,
) -> tuple[BuildCommand, ...]:
    if android_init == "skip":
        if _app_product(app) == "chat":
            return (
                BuildCommand(
                    description=f"Verify Android native patches for {app.app_dir}",
                    command=_npm_command("tauri:android:prepare:check"),
                    cwd=app.app_root(project_root),
                    env=env,
                ),
            )
        return ()

    should_init = android_init == "always" or not _android_gen_exists(app, project_root)
    commands: list[BuildCommand] = []
    if should_init:
        commands.append(
            BuildCommand(
                description=f"Initialize Android project for {app.app_dir}",
                command=("npm", "run", "tauri:android:init"),
                cwd=app.app_root(project_root),
                env=env,
            )
        )
    if _app_product(app) == "chat":
        commands.append(
            BuildCommand(
                description="Verify Chat Android native patches",
                command=("npm", "run", "tauri:android:prepare:check"),
                cwd=app.app_root(project_root),
                env=env,
            )
        )
    return tuple(commands)


def _build_output_dir(project_root: Path) -> Path:
    suffix = "local"
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        suffix = result.stdout.strip()
    return project_root / "dist" / "native" / suffix


def make_build_tasks(
    options: BuildOptions,
    *,
    project_root: Path = _PROJECT_ROOT,
) -> tuple[BuildTask, ...]:
    root = project_root.resolve()
    env = build_environment(root)
    tasks: list[BuildTask] = []
    for app in selected_apps(options.product):
        app_root = app.app_root(root)
        install_once_commands: tuple[BuildCommand, ...]
        install_planned = False
        android_init_planned = False
        if _needs_npm_ci(app, root, options.no_install_deps):
            install_once_commands = (
                BuildCommand(
                    description=f"Install npm dependencies for {app.app_dir}",
                    command=("npm", "ci"),
                    cwd=app_root,
                    env=env,
                ),
            )
        else:
            install_once_commands = ()

        for target_kind in selected_target_kinds(options.targets):
            install_commands = install_once_commands if not install_planned else ()
            if install_commands:
                install_planned = True
            if target_kind == "desktop":
                if not _is_linux():
                    raise RuntimeError(
                        "Local desktop builds are only supported on Linux"
                    )
                bundle_arg = desktop_bundle_arg(options.desktop_bundles)
                tasks.append(
                    BuildTask(
                        product=_app_product(app),
                        target_kind="desktop",
                        label="linux-x64",
                        app=app,
                        commands=(
                            *install_commands,
                            BuildCommand(
                                description=f"Build Linux desktop bundles for {app.app_dir}",
                                command=_npm_command(
                                    "tauri:build",
                                    ("--ci", "--bundles", bundle_arg),
                                ),
                                cwd=app_root,
                                env={**env, "NO_STRIP": "true"},
                            ),
                        ),
                        artifact_patterns=tuple(
                            pattern
                            for bundle in bundle_arg.split(",")
                            for pattern in (
                                ("*.deb",) if bundle == "deb" else ("*.AppImage",)
                            )
                        ),
                        artifact_search_root=app.tauri_root(root)
                        / "target"
                        / "release"
                        / "bundle",
                    )
                )
            elif target_kind == "android":
                for android_target in selected_android_targets(options.android_abi):
                    android_init_commands = (
                        ()
                        if android_init_planned
                        else _android_init_commands(
                            app,
                            root,
                            env,
                            options.android_init,
                        )
                    )
                    android_init_planned = True
                    tasks.append(
                        BuildTask(
                            product=_app_product(app),
                            target_kind="android",
                            label=android_target.abi_label,
                            app=app,
                            commands=(
                                *install_commands,
                                *android_init_commands,
                                BuildCommand(
                                    description=(
                                        f"Build Android debug APK for {app.app_dir} "
                                        f"{android_target.abi_label}"
                                    ),
                                    command=_npm_command(
                                        "tauri:android:debug",
                                        (
                                            "--ci",
                                            "--apk",
                                            "--target",
                                            android_target.tauri_target,
                                        ),
                                    ),
                                    cwd=app_root,
                                    env=env,
                                ),
                            ),
                            artifact_patterns=("*.apk",),
                            artifact_search_root=app.tauri_root(root),
                        )
                    )
                    install_commands = ()
            else:
                raise AssertionError(f"Unhandled target kind: {target_kind}")
    return tuple(tasks)


def _which(command: str, env: dict[str, str]) -> str | None:
    return shutil.which(command, path=env.get("PATH"))


def _command_output(command: Sequence[str], env: dict[str, str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        return 127, str(exc)
    return result.returncode, result.stdout.strip()


def _java_version_ok(env: dict[str, str]) -> CheckItem:
    java = _which("java", env)
    if java is None:
        return CheckItem(
            "Java 17",
            False,
            "java not found",
            "安装 jdk17-openjdk，并设置 JAVA_HOME=/usr/lib/jvm/java-17-openjdk",
        )
    code, output = _command_output(("java", "-version"), env)
    ok = code == 0 and ('version "17.' in output or "openjdk 17." in output.lower())
    return CheckItem(
        "Java 17",
        ok,
        output.splitlines()[0] if output else java,
        None if ok else "设置 JAVA_HOME=/usr/lib/jvm/java-17-openjdk 后重试",
    )


def _rust_target_installed(rust_target: str, env: dict[str, str]) -> bool:
    code, output = _command_output(("rustup", "target", "list", "--installed"), env)
    if code != 0:
        return False
    return rust_target in output.splitlines()


def check_environment(
    *,
    project_root: Path = _PROJECT_ROOT,
    targets: str,
    android_abi: str,
) -> tuple[CheckItem, ...]:
    root = project_root.resolve()
    env = build_environment(root)
    items: list[CheckItem] = []
    for command in ("node", "npm", "cargo", "rustup"):
        path = _which(command, env)
        items.append(
            CheckItem(
                command,
                path is not None,
                path or f"{command} not found",
                None if path else f"请先安装 {command}",
            )
        )

    target_kinds = selected_target_kinds(targets)
    if "desktop" in target_kinds:
        items.append(
            CheckItem(
                "Linux desktop host",
                _is_linux(),
                platform.system(),
                None if _is_linux() else "本地桌面构建只支持当前 Linux 主机",
            )
        )

    if "android" in target_kinds:
        items.append(_java_version_ok(env))
        sdk_root = Path(env["ANDROID_HOME"])
        ndk_home = Path(env["NDK_HOME"])
        sdkmanager = _which("sdkmanager", env)
        items.append(
            CheckItem(
                "sdkmanager",
                sdkmanager is not None,
                sdkmanager or "sdkmanager not found",
                None
                if sdkmanager
                else "source /etc/profile 或把 Android cmdline-tools/latest/bin 加入 PATH",
            )
        )
        for relative in (
            Path("platform-tools"),
            Path("platforms") / "android-34",
            Path("build-tools") / "34.0.0",
        ):
            sdk_path = sdk_root / relative
            items.append(
                CheckItem(
                    str(relative),
                    sdk_path.exists(),
                    str(sdk_path),
                    None
                    if sdk_path.exists()
                    else "运行 sdkmanager 安装 platform-tools/platforms;android-34/build-tools;34.0.0",
                )
            )
        items.append(
            CheckItem(
                "Android NDK",
                ndk_home.exists(),
                str(ndk_home),
                None
                if ndk_home.exists()
                else f'运行 sdkmanager --install "ndk;{ANDROID_NDK_VERSION}"',
            )
        )
        for android_target in selected_android_targets(android_abi):
            ok = _rust_target_installed(android_target.rust_target, env)
            items.append(
                CheckItem(
                    f"Rust target {android_target.rust_target}",
                    ok,
                    "installed" if ok else "missing",
                    None if ok else f"rustup target add {android_target.rust_target}",
                )
            )
    return tuple(items)


def _run_command(command: BuildCommand, dry_run: bool) -> None:
    printable = " ".join(command.command)
    print(f"\n==> {command.description}")
    print(f"    cd {command.cwd}")
    print(f"    {printable}")
    if dry_run:
        return
    subprocess.run(
        list(command.command),
        cwd=command.cwd,
        env=command.env,
        check=True,
    )


def _artifact_matches(task: BuildTask) -> tuple[Path, ...]:
    matches: list[Path] = []
    for pattern in task.artifact_patterns:
        matches.extend(
            path
            for path in task.artifact_search_root.rglob(pattern)
            if not path.name.endswith("-unsigned.apk")
        )
    return tuple(sorted(set(matches)))


def _artifact_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _artifact_snapshot(task: BuildTask) -> dict[Path, tuple[int, int]]:
    return {path: _artifact_signature(path) for path in _artifact_matches(task)}


def _copy_artifacts(
    task: BuildTask,
    output_dir: Path,
    matches: Iterable[Path],
    *,
    dry_run: bool,
) -> tuple[Path, ...]:
    collected: list[Path] = []
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    for source in matches:
        destination = (
            output_dir
            / f"{task.app.artifact_prefix}-{task.target_kind}-{task.label}-{source.name}"
        )
        print(f"Collect {source} -> {destination}")
        if not dry_run:
            shutil.copy2(source, destination)
        collected.append(destination)
    return tuple(collected)


def collect_new_artifacts(
    task: BuildTask,
    output_dir: Path,
    before: dict[Path, tuple[int, int]],
    *,
    dry_run: bool,
) -> tuple[Path, ...]:
    after = _artifact_snapshot(task)
    matches = tuple(
        path
        for path, signature in sorted(after.items())
        if before.get(path) != signature
    )
    if not matches:
        raise FileNotFoundError(
            f"No new artifacts found for {task.app.app_dir} {task.target_kind} {task.label} "
            f"under {task.artifact_search_root}"
        )
    return _copy_artifacts(task, output_dir, matches, dry_run=dry_run)


def collect_artifacts(
    tasks: Iterable[BuildTask],
    output_dir: Path,
    *,
    dry_run: bool,
) -> tuple[Path, ...]:
    collected: list[Path] = []
    for task in tasks:
        matches = _artifact_matches(task)
        if not matches:
            raise FileNotFoundError(
                f"No artifacts found for {task.app.app_dir} {task.target_kind} {task.label} "
                f"under {task.artifact_search_root}"
            )
        collected.extend(_copy_artifacts(task, output_dir, matches, dry_run=dry_run))
    return tuple(collected)


def print_check_items(items: Iterable[CheckItem]) -> bool:
    all_ok = True
    for item in items:
        status = "OK" if item.ok else "MISS"
        print(f"[{status}] {item.name}: {item.detail}")
        if not item.ok:
            all_ok = False
            if item.fix_hint:
                print(f"       fix: {item.fix_hint}")
    return all_ok


def command_list(args: argparse.Namespace) -> int:
    options = options_from_args(args)
    tasks = make_build_tasks(options)
    for task in tasks:
        print(f"{task.product} {task.target_kind} {task.label}:")
        for command in task.commands:
            print(f"  - {command.description}: {' '.join(command.command)}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    items = check_environment(targets=args.targets, android_abi=args.android_abi)
    return 0 if print_check_items(items) else 1


def command_build(args: argparse.Namespace) -> int:
    options = options_from_args(args)
    check_items = check_environment(
        targets=options.targets, android_abi=options.android_abi
    )
    if not print_check_items(check_items):
        print("\n环境检查未通过；脚本不会自动安装依赖。请按 fix 提示补齐后重试。")
        return 1
    tasks = make_build_tasks(options)
    collected: list[Path] = []
    for task in tasks:
        before = _artifact_snapshot(task) if not options.dry_run else {}
        for command in task.commands:
            _run_command(command, options.dry_run)
        if not options.dry_run:
            collected.extend(
                collect_new_artifacts(
                    task,
                    options.output_dir,
                    before,
                    dry_run=False,
                )
            )
    if options.dry_run:
        return 0
    print("\nArtifacts:")
    for path in collected:
        print(f"  {path}")
    return 0


def options_from_args(args: argparse.Namespace) -> BuildOptions:
    output_dir = (
        Path(args.output_dir) if args.output_dir else _build_output_dir(_PROJECT_ROOT)
    )
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    return BuildOptions(
        product=args.product,
        targets=args.targets,
        android_abi=args.android_abi,
        desktop_bundles=args.desktop_bundles,
        output_dir=output_dir,
        dry_run=args.dry_run,
        no_install_deps=args.no_install_deps,
        android_init=args.android_init,
    )


def _add_common_args(parser: argparse.ArgumentParser, *, include_build: bool) -> None:
    parser.add_argument("--product", choices=PRODUCT_CHOICES, default="chat")
    parser.add_argument("--targets", choices=TARGET_CHOICES, default="android")
    parser.add_argument(
        "--android-abi", choices=ANDROID_ABI_CHOICES, default="arm64-v8a"
    )
    if include_build:
        parser.add_argument(
            "--desktop-bundles", choices=DESKTOP_BUNDLE_CHOICES, default="deb"
        )
        parser.add_argument("--output-dir")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-install-deps", action="store_true")
        parser.add_argument(
            "--android-init", choices=ANDROID_INIT_CHOICES, default="auto"
        )
    else:
        parser.set_defaults(
            desktop_bundles="deb",
            output_dir=None,
            dry_run=False,
            no_install_deps=False,
            android_init="auto",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build local Undefined native app artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Print selected local build tasks")
    _add_common_args(list_parser, include_build=True)
    list_parser.set_defaults(func=command_list)

    check_parser = subparsers.add_parser(
        "check", help="Check local build prerequisites"
    )
    _add_common_args(check_parser, include_build=False)
    check_parser.set_defaults(func=command_check)

    build = subparsers.add_parser("build", help="Build selected local artifacts")
    _add_common_args(build, include_build=True)
    build.set_defaults(func=command_build)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
