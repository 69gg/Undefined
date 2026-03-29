from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from Undefined.utils.resources import resolve_resource_path

CHANGELOG_FILENAME = "CHANGELOG.md"
_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_HEADING_RE = re.compile(r"^(#{2,6})\s+(v\d+\.\d+\.\d+)\s+(.+?)\s*$")
_SEPARATOR_RE = re.compile(r"(?m)^\s*---\s*$")
_BULLET_RE = re.compile(r"^\s*-\s+(.+?)\s*$")


class ChangelogError(ValueError):
    """Base error for changelog loading failures."""


class ChangelogFormatError(ChangelogError):
    """Raised when CHANGELOG.md does not match the expected format."""


@dataclass(frozen=True, slots=True)
class ChangelogEntry:
    version: str
    title: str
    summary: str
    changes: tuple[str, ...]
    heading_level: int = 2


def normalize_version(version: str) -> str:
    normalized = str(version or "").strip()
    if not normalized:
        raise ChangelogFormatError("版本号不能为空")
    if normalized[:1].lower() == "v":
        normalized = normalized[1:]
    normalized = f"v{normalized}"
    if not _VERSION_RE.fullmatch(normalized):
        raise ChangelogFormatError(f"非法版本号格式: {version}")
    return normalized


def resolve_changelog_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return resolve_resource_path(CHANGELOG_FILENAME)


def load_changelog(path: str | Path | None = None) -> tuple[ChangelogEntry, ...]:
    changelog_path = resolve_changelog_path(path)
    text = changelog_path.read_text(encoding="utf-8")
    return parse_changelog_text(text)


def parse_changelog_text(text: str) -> tuple[ChangelogEntry, ...]:
    normalized = str(text or "").strip()
    if not normalized:
        raise ChangelogFormatError("CHANGELOG 内容为空")

    entries: list[ChangelogEntry] = []
    seen_versions: set[str] = set()
    for block in _SEPARATOR_RE.split(normalized):
        stripped = block.strip()
        if not stripped:
            continue
        entry = _parse_entry_block(stripped)
        if entry.version in seen_versions:
            raise ChangelogFormatError(f"发现重复版本: {entry.version}")
        seen_versions.add(entry.version)
        entries.append(entry)

    if not entries:
        raise ChangelogFormatError("未解析到任何版本条目")
    return tuple(entries)


def _parse_entry_block(block: str) -> ChangelogEntry:
    lines = block.splitlines()
    if not lines:
        raise ChangelogFormatError("发现空版本块")

    heading_match = _HEADING_RE.fullmatch(lines[0].strip())
    if heading_match is None:
        raise ChangelogFormatError(f"标题行格式错误: {lines[0]}")

    heading_hashes, version, raw_title = heading_match.groups()
    title = raw_title.strip()
    if not title:
        raise ChangelogFormatError(f"{version} 缺少标题")

    summary_lines: list[str] = []
    changes: list[str] = []
    bullet_started = False

    for raw_line in lines[1:]:
        bullet_match = _BULLET_RE.fullmatch(raw_line)
        if bullet_match is not None:
            bullet_started = True
            changes.append(bullet_match.group(1).strip())
            continue
        if bullet_started:
            if raw_line.strip():
                raise ChangelogFormatError(
                    f"{version} 的变更列表后存在非法内容: {raw_line}"
                )
            continue
        summary_lines.append(raw_line.strip() if raw_line.strip() else "")

    summary = "\n".join(_normalize_summary_lines(summary_lines)).strip()
    if not summary:
        raise ChangelogFormatError(f"{version} 缺少摘要")
    if not changes:
        raise ChangelogFormatError(f"{version} 缺少变更点")

    return ChangelogEntry(
        version=version,
        title=title,
        summary=summary,
        changes=tuple(changes),
        heading_level=len(heading_hashes),
    )


def _normalize_summary_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    for line in lines:
        if line.strip():
            normalized.append(line.strip())
        else:
            normalized.append("")
    return normalized


def get_latest_entry(
    *,
    entries: tuple[ChangelogEntry, ...] | None = None,
    path: str | Path | None = None,
) -> ChangelogEntry:
    resolved_entries = entries if entries is not None else load_changelog(path)
    return resolved_entries[0]


def list_entries(
    *,
    limit: int | None = None,
    entries: tuple[ChangelogEntry, ...] | None = None,
    path: str | Path | None = None,
) -> tuple[ChangelogEntry, ...]:
    resolved_entries = entries if entries is not None else load_changelog(path)
    if limit is None:
        return resolved_entries
    if limit <= 0:
        raise ChangelogFormatError("limit 必须大于 0")
    return resolved_entries[:limit]


def get_entry(
    version: str,
    *,
    entries: tuple[ChangelogEntry, ...] | None = None,
    path: str | Path | None = None,
) -> ChangelogEntry:
    normalized = normalize_version(version)
    resolved_entries = entries if entries is not None else load_changelog(path)
    for entry in resolved_entries:
        if entry.version == normalized:
            return entry
    raise ChangelogError(f"未找到版本: {normalized}")


def entry_to_dict(
    entry: ChangelogEntry,
    *,
    include_summary: bool = True,
    include_changes: bool = True,
    max_changes: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": entry.version,
        "title": entry.title,
    }
    if include_summary:
        payload["summary"] = entry.summary
    if include_changes:
        changes = list(entry.changes)
        if max_changes is not None:
            if max_changes <= 0:
                raise ChangelogFormatError("max_changes 必须大于 0")
            changes = changes[:max_changes]
        payload["changes"] = changes
        payload["change_count"] = len(entry.changes)
    return payload


__all__ = [
    "CHANGELOG_FILENAME",
    "ChangelogEntry",
    "ChangelogError",
    "ChangelogFormatError",
    "entry_to_dict",
    "get_entry",
    "get_latest_entry",
    "list_entries",
    "load_changelog",
    "normalize_version",
    "parse_changelog_text",
    "resolve_changelog_path",
]
