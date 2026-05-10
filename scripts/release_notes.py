#!/usr/bin/env python3
"""Validate release versions and render GitHub release notes from CHANGELOG.md."""

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
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from Undefined.changelog import (  # noqa: E402
    ChangelogEntry,
    normalize_version,
    parse_changelog_text,
)


class ReleaseValidationError(ValueError):
    """Raised when release metadata is inconsistent."""


@dataclass(frozen=True, slots=True)
class VersionSource:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class ReleaseValidationResult:
    version: str
    changelog_version: str
    tag_version: str | None
    sources: tuple[VersionSource, ...]


@dataclass(frozen=True, slots=True)
class DetailedChangeSection:
    heading: str
    commits: tuple[str, ...]


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise ReleaseValidationError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def _run_git(
    project_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        command = " ".join(("git", *args))
        raise ReleaseValidationError(
            f"Git command failed while generating release notes: {command}\n"
            f"{result.stderr.strip()}"
        )
    return result


def _git_stdout(project_root: Path, *args: str, check: bool = True) -> str:
    return _run_git(project_root, *args, check=check).stdout.strip()


def _require_non_empty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseValidationError(f"Missing required version value: {label}")
    return value.strip()


def _read_pyproject_version(project_root: Path) -> str:
    path = project_root / "pyproject.toml"
    data = tomllib.loads(_read_required_text(path))
    project = data.get("project")
    if not isinstance(project, dict):
        raise ReleaseValidationError("pyproject.toml is missing [project]")
    return _require_non_empty_string(
        project.get("version"), "pyproject.toml project.version"
    )


def _read_init_version(project_root: Path) -> str:
    path = project_root / "src" / "Undefined" / "__init__.py"
    text = _read_required_text(path)
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if match is None:
        raise ReleaseValidationError(
            "Could not find __version__ in src/Undefined/__init__.py"
        )
    return match.group(1).strip()


def _read_json_file(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_read_required_text(path)))


def _read_json_version(project_root: Path, relative_path: str) -> str:
    path = project_root / relative_path
    data = _read_json_file(path)
    return _require_non_empty_string(data.get("version"), f"{relative_path} version")


def _read_package_lock_root_version(project_root: Path) -> str:
    relative_path = "apps/undefined-console/package-lock.json"
    data = _read_json_file(project_root / relative_path)
    packages = data.get("packages")
    if not isinstance(packages, dict):
        raise ReleaseValidationError(f"{relative_path} is missing packages")
    root_package = packages.get("")
    if not isinstance(root_package, dict):
        raise ReleaseValidationError(f'{relative_path} is missing packages[""]')
    return _require_non_empty_string(
        root_package.get("version"), f'{relative_path} packages[""].version'
    )


def _read_cargo_version(project_root: Path) -> str:
    relative_path = "apps/undefined-console/src-tauri/Cargo.toml"
    path = project_root / relative_path
    data = tomllib.loads(_read_required_text(path))
    package = data.get("package")
    if not isinstance(package, dict):
        raise ReleaseValidationError(f"{relative_path} is missing [package]")
    return _require_non_empty_string(
        package.get("version"), f"{relative_path} package.version"
    )


def read_build_version_sources(
    project_root: Path = _PROJECT_ROOT,
) -> tuple[VersionSource, ...]:
    root = project_root.resolve()
    return (
        VersionSource("pyproject.toml", _read_pyproject_version(root)),
        VersionSource("src/Undefined/__init__.py", _read_init_version(root)),
        VersionSource(
            "apps/undefined-console/package.json",
            _read_json_version(root, "apps/undefined-console/package.json"),
        ),
        VersionSource(
            'apps/undefined-console/package-lock.json packages[""]',
            _read_package_lock_root_version(root),
        ),
        VersionSource(
            "apps/undefined-console/src-tauri/Cargo.toml", _read_cargo_version(root)
        ),
        VersionSource(
            "apps/undefined-console/src-tauri/tauri.conf.json",
            _read_json_version(
                root, "apps/undefined-console/src-tauri/tauri.conf.json"
            ),
        ),
    )


def read_latest_changelog_entry(project_root: Path = _PROJECT_ROOT) -> ChangelogEntry:
    path = project_root.resolve() / "CHANGELOG.md"
    entries = parse_changelog_text(_read_required_text(path))
    return entries[0]


def validate_release_versions(
    *,
    tag_name: str | None,
    project_root: Path = _PROJECT_ROOT,
) -> ReleaseValidationResult:
    sources = read_build_version_sources(project_root)
    base_version = sources[0].version
    changelog_entry = read_latest_changelog_entry(project_root)
    changelog_version = changelog_entry.version.removeprefix("v")
    tag_version = normalize_version(tag_name).removeprefix("v") if tag_name else None

    errors: list[str] = []
    for source in sources[1:]:
        if source.version != base_version:
            errors.append(
                f"Version mismatch: pyproject.toml={base_version}, {source.name}={source.version}"
            )
    if changelog_version != base_version:
        errors.append(
            "Version mismatch: "
            f"pyproject.toml={base_version}, CHANGELOG.md latest={changelog_entry.version}"
        )
    if tag_version is not None and tag_version != base_version:
        errors.append(
            f"Tag/version mismatch: tag={tag_name}, expected build version={tag_version}, actual={base_version}"
        )

    if errors:
        raise ReleaseValidationError("\n".join(errors))

    return ReleaseValidationResult(
        version=base_version,
        changelog_version=changelog_entry.version,
        tag_version=tag_version,
        sources=sources,
    )


def render_release_notes(entry: ChangelogEntry) -> str:
    lines = [f"## {entry.version} {entry.title}", ""]
    lines.extend(entry.summary.splitlines())
    lines.extend(["", "### 变更内容", ""])
    lines.extend(f"- {change}" for change in entry.changes)
    return "\n".join(lines).rstrip() + "\n"


def _previous_release_ref(project_root: Path, tag_name: str) -> str:
    normalized_tag = normalize_version(tag_name)
    previous_tag = _git_stdout(
        project_root,
        "describe",
        "--tags",
        "--abbrev=0",
        f"{normalized_tag}^",
        check=False,
    )
    if previous_tag:
        return previous_tag
    return _git_stdout(project_root, "rev-list", "--max-parents=0", "HEAD")


def _categorized_commits(
    project_root: Path,
    revision_range: str,
    *,
    grep: str,
    invert_grep: bool = False,
) -> tuple[str, ...]:
    args = ["log", revision_range, f"--grep={grep}"]
    if invert_grep:
        args.append("--invert-grep")
    args.append("--pretty=format:* %s (%h)")
    output = _git_stdout(project_root, *args)
    if not output:
        return ()
    return tuple(line for line in output.splitlines() if line.strip())


def build_detailed_change_sections(
    *,
    tag_name: str,
    project_root: Path = _PROJECT_ROOT,
) -> tuple[DetailedChangeSection, ...]:
    root = project_root.resolve()
    normalized_tag = normalize_version(tag_name)
    previous_ref = _previous_release_ref(root, normalized_tag)
    revision_range = f"{previous_ref}..{normalized_tag}"
    return (
        DetailedChangeSection(
            "### 🚀 Features",
            _categorized_commits(root, revision_range, grep="^feat"),
        ),
        DetailedChangeSection(
            "### 🐛 Bug Fixes",
            _categorized_commits(root, revision_range, grep="^fix"),
        ),
        DetailedChangeSection(
            "### 🛠 Maintenance & Others",
            _categorized_commits(
                root,
                revision_range,
                grep="^feat\\|^fix",
                invert_grep=True,
            ),
        ),
    )


def render_detailed_changes(
    *,
    tag_name: str,
    project_root: Path = _PROJECT_ROOT,
) -> str:
    lines = ["## 📝 Detailed Changes"]
    has_commits = False
    for section in build_detailed_change_sections(
        tag_name=tag_name, project_root=project_root
    ):
        if not section.commits:
            continue
        has_commits = True
        lines.extend(["", section.heading])
        lines.extend(section.commits)
    if not has_commits:
        lines.extend(["", "_No commit details found for this release._"])
    return "\n".join(lines).rstrip() + "\n"


def render_full_release_notes(
    *,
    entry: ChangelogEntry,
    tag_name: str,
    project_root: Path = _PROJECT_ROOT,
) -> str:
    changelog_notes = render_release_notes(entry).rstrip()
    detailed_changes = render_detailed_changes(
        tag_name=tag_name, project_root=project_root
    ).rstrip()
    return f"{changelog_notes}\n\n---\n\n{detailed_changes}\n"


def write_release_notes(
    *,
    output_path: Path,
    tag_name: str | None,
    project_root: Path = _PROJECT_ROOT,
) -> ChangelogEntry:
    validate_release_versions(tag_name=tag_name, project_root=project_root)
    entry = read_latest_changelog_entry(project_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_full_release_notes(
            entry=entry,
            tag_name=tag_name or entry.version,
            project_root=project_root,
        ),
        encoding="utf-8",
    )
    return entry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Release metadata helper")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
        help="Repository root, defaults to the parent of scripts/",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate release tag, build versions, and CHANGELOG latest version",
    )
    validate_parser.add_argument(
        "--tag", required=True, help="Release tag, such as v3.4.0"
    )

    notes_parser = subparsers.add_parser(
        "notes", help="write GitHub release notes from CHANGELOG.md latest version"
    )
    notes_parser.add_argument(
        "--tag", required=True, help="Release tag, such as v3.4.0"
    )
    notes_parser.add_argument(
        "--output", type=Path, required=True, help="Output markdown file"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = cast(Path, args.project_root).resolve()

    try:
        if args.command == "validate":
            result = validate_release_versions(
                tag_name=cast(str, args.tag), project_root=project_root
            )
            source_names = ", ".join(source.name for source in result.sources)
            print(
                "Validated release version "
                f"{result.version} from tag v{result.tag_version}, {source_names}, "
                f"and CHANGELOG.md latest {result.changelog_version}"
            )
            return 0
        if args.command == "notes":
            entry = write_release_notes(
                output_path=cast(Path, args.output),
                tag_name=cast(str, args.tag),
                project_root=project_root,
            )
            print(f"Wrote release notes for {entry.version} to {args.output}")
            return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
