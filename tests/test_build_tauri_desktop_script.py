from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_tauri_desktop.sh"


def _run_build(
    tmp_path: Path,
    *,
    runner_os: str = "macOS",
    bundles: str = "dmg",
    rust_target: str = "",
    build_error: str = "",
    build_exit_code: int = 0,
    bundle_exit_code: int = 0,
    workflow_run: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s|%s|%s\\n" "$CI" "${NO_STRIP:-unset}" "$*" '
        '>> "$TEST_COMMAND_LOG"\n'
        'if [[ "$2" == "tauri:build" ]]; then\n'
        '  printf "%s\\n" "$TEST_BUILD_ERROR" >&2\n'
        '  exit "$TEST_BUILD_EXIT_CODE"\n'
        "fi\n"
        'exit "$TEST_BUNDLE_EXIT_CODE"\n',
        encoding="utf-8",
    )
    npm.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text(
        '#!/usr/bin/env bash\nprintf "sleep %s\\n" "$*" >> "$TEST_COMMAND_LOG"\n',
        encoding="utf-8",
    )
    sleep.chmod(0o755)
    env = {
        **os.environ,
        "CI": "true" if workflow_run is not None else "false",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "RUNNER_OS": runner_os,
        "TAURI_BUNDLES": bundles,
        "TAURI_RUST_TARGET": rust_target,
        "TEST_COMMAND_LOG": str(command_log),
        "TEST_BUILD_ERROR": build_error,
        "TEST_BUILD_EXIT_CODE": str(build_exit_code),
        "TEST_BUNDLE_EXIT_CODE": str(bundle_exit_code),
    }
    env.pop("NO_STRIP", None)
    app_dir = tmp_path / "apps" / "test-app"
    app_dir.mkdir(parents=True)
    command = (
        ["bash", "-c", workflow_run]
        if workflow_run is not None
        else ["bash", str(SCRIPT_PATH), bundles, rust_target]
    )
    result = subprocess.run(
        command,
        cwd=app_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return result, command_log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("runner_os", "bundles", "no_strip"),
    [
        ("Linux", "appimage,deb", "true"),
        ("Windows", "nsis,msi", "unset"),
        ("macOS", "dmg", "unset"),
    ],
)
def test_successful_build_does_not_retry(
    tmp_path: Path, runner_os: str, bundles: str, no_strip: str
) -> None:
    result, commands = _run_build(tmp_path, runner_os=runner_os, bundles=bundles)

    assert result.returncode == 0, result.stderr
    expected = f"true|{no_strip}|run tauri:build -- --ci --bundles {bundles}"
    if runner_os == "macOS":
        expected += " --verbose"
    assert commands == [expected]


def test_dmg_script_failure_retries_only_packaging_with_the_same_target(
    tmp_path: Path,
) -> None:
    result, commands = _run_build(
        tmp_path,
        rust_target="x86_64-apple-darwin",
        build_error="failed to bundle project error running bundle_dmg.sh: failed to run",
        build_exit_code=1,
    )

    assert result.returncode == 0, result.stderr
    args = "--ci --bundles dmg --target x86_64-apple-darwin --verbose"
    assert commands == [
        f"true|unset|run tauri:build -- {args}",
        "sleep 5",
        f"true|unset|run tauri -- bundle {args}",
    ]
    assert "error running bundle_dmg.sh" in result.stdout


def test_persistent_dmg_failure_preserves_the_retry_exit_code(tmp_path: Path) -> None:
    result, commands = _run_build(
        tmp_path,
        build_error="error running bundle_dmg.sh",
        build_exit_code=1,
        bundle_exit_code=17,
    )

    assert result.returncode == 17
    assert len(commands) == 3
    assert commands[-1].startswith("true|unset|run tauri -- bundle ")


@pytest.mark.parametrize(
    ("runner_os", "bundles", "build_error"),
    [
        ("macOS", "dmg", "Rust compilation failed"),
        ("macOS", "dmg", "Code signing failed"),
        ("macOS", "app", "error running bundle_dmg.sh"),
        ("Linux", "appimage,deb", "error running bundle_dmg.sh"),
        ("Windows", "nsis,msi", "error running bundle_dmg.sh"),
    ],
)
def test_other_failures_are_not_retried(
    tmp_path: Path, runner_os: str, bundles: str, build_error: str
) -> None:
    result, commands = _run_build(
        tmp_path,
        runner_os=runner_os,
        bundles=bundles,
        build_error=build_error,
        build_exit_code=42,
    )

    assert result.returncode == 42
    assert len(commands) == 1


@pytest.mark.parametrize(
    ("workflow_name", "job_name"),
    [
        ("release", "build-tauri-desktop"),
        ("manual-native-artifacts", "build-desktop"),
    ],
)
def test_desktop_workflows_use_the_shared_build_script(
    workflow_name: str, job_name: str
) -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / f"{workflow_name}.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_name]["steps"]
    build_step = next(
        step for step in steps if step.get("name") == "Build Tauri bundles"
    )

    assert build_step["working-directory"] == "${{ matrix.app_dir }}"
    assert build_step["shell"] == "bash"
    assert build_step["env"]["TAURI_BUNDLES"] == "${{ matrix.bundles }}"
    assert build_step["env"]["TAURI_RUST_TARGET"] == "${{ matrix.rust_target }}"
    assert (
        'bash ../../scripts/build_tauri_desktop.sh "$TAURI_BUNDLES" "$TAURI_RUST_TARGET"'
        in build_step["run"]
    )


@pytest.mark.parametrize(
    ("runner_os", "bundles", "rust_target", "exit_code"),
    [
        ("Linux", "appimage,deb", "", 0),
        ("Windows", "nsis,msi", "", 0),
        ("macOS", "dmg", "x86_64-apple-darwin", 0),
        ("macOS", "dmg", "x86_64-apple-darwin", 42),
    ],
)
def test_manual_workflow_can_build_old_refs_without_the_shared_script(
    tmp_path: Path, runner_os: str, bundles: str, rust_target: str, exit_code: int
) -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "manual-native-artifacts.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["build-desktop"]["steps"]
    build_step = next(
        step for step in steps if step.get("name") == "Build Tauri bundles"
    )
    result, commands = _run_build(
        tmp_path,
        runner_os=runner_os,
        bundles=bundles,
        rust_target=rust_target,
        build_exit_code=exit_code,
        workflow_run=build_step["run"],
    )

    assert result.returncode == exit_code, result.stderr
    no_strip = "true" if runner_os == "Linux" else "unset"
    expected = f"true|{no_strip}|run tauri:build -- --ci --bundles {bundles}"
    if rust_target:
        expected += f" --target {rust_target}"
    assert commands == [expected]
