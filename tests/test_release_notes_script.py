from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "release_notes.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_notes_script", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load release_notes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_notes = _load_script()


def _write_release_project(
    root: Path,
    *,
    build_version: str = "1.2.3",
    changelog_version: str = "v1.2.3",
) -> None:
    (root / "src" / "Undefined").mkdir(parents=True)
    (root / "apps" / "undefined-console" / "src-tauri").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "Undefined-bot"\nversion = "{build_version}"\n',
        encoding="utf-8",
    )
    (root / "src" / "Undefined" / "__init__.py").write_text(
        f'__version__ = "{build_version}"\n',
        encoding="utf-8",
    )
    (root / "apps" / "undefined-console" / "package.json").write_text(
        f'{{"version":"{build_version}"}}\n',
        encoding="utf-8",
    )
    (root / "apps" / "undefined-console" / "package-lock.json").write_text(
        f'{{"version":"{build_version}","packages":{{"":{{"version":"{build_version}"}}}}}}\n',
        encoding="utf-8",
    )
    (root / "apps" / "undefined-console" / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "undefined-console"\nversion = "{build_version}"\n',
        encoding="utf-8",
    )
    (root / "apps" / "undefined-console" / "src-tauri" / "tauri.conf.json").write_text(
        f'{{"version":"{build_version}"}}\n',
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text(
        f"""
## {changelog_version} 测试版本

这是一段发布说明。

- 变更一
- 变更二
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_validate_release_versions_accepts_matching_project(tmp_path: Path) -> None:
    _write_release_project(tmp_path)

    result = release_notes.validate_release_versions(
        tag_name="v1.2.3", project_root=tmp_path
    )

    assert result.version == "1.2.3"
    assert result.changelog_version == "v1.2.3"
    assert result.tag_version == "1.2.3"
    assert {source.name for source in result.sources} >= {
        "pyproject.toml",
        "src/Undefined/__init__.py",
        "apps/undefined-console/package.json",
        "apps/undefined-console/src-tauri/Cargo.toml",
    }


def test_validate_release_versions_rejects_changelog_mismatch(tmp_path: Path) -> None:
    _write_release_project(tmp_path, build_version="1.2.3", changelog_version="v1.2.4")

    with pytest.raises(
        release_notes.ReleaseValidationError, match="CHANGELOG.md latest"
    ):
        release_notes.validate_release_versions(
            tag_name="v1.2.3", project_root=tmp_path
        )


def test_validate_release_versions_rejects_app_manifest_mismatch(
    tmp_path: Path,
) -> None:
    _write_release_project(tmp_path)
    (tmp_path / "apps" / "undefined-console" / "package.json").write_text(
        '{"version":"1.2.4"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        release_notes.ReleaseValidationError, match="package.json=1.2.4"
    ):
        release_notes.validate_release_versions(
            tag_name="v1.2.3", project_root=tmp_path
        )


def test_write_release_notes_uses_latest_changelog_entry(tmp_path: Path) -> None:
    _write_release_project(tmp_path)
    output = tmp_path / "release_notes.md"

    entry = release_notes.write_release_notes(
        output_path=output,
        tag_name="v1.2.3",
        project_root=tmp_path,
    )

    assert entry.version == "v1.2.3"
    assert output.read_text(encoding="utf-8") == (
        "## v1.2.3 测试版本\n"
        "\n"
        "这是一段发布说明。\n"
        "\n"
        "### 变更内容\n"
        "\n"
        "- 变更一\n"
        "- 变更二\n"
    )


def test_cli_notes_writes_output_file(tmp_path: Path) -> None:
    _write_release_project(tmp_path)
    output = tmp_path / "notes.md"

    exit_code = cast(
        Any,
        release_notes.main,
    )(
        [
            "--project-root",
            str(tmp_path),
            "notes",
            "--tag",
            "v1.2.3",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.read_text(encoding="utf-8").startswith("## v1.2.3 测试版本")
