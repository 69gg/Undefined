from __future__ import annotations

from typing import Any
import json

from Undefined.changelog import (
    ChangelogError,
    ChangelogFormatError,
    entry_to_dict,
    get_entry,
    get_latest_entry,
    list_entries,
)

_DEFAULT_LIST_LIMIT = 5
_MAX_LIST_LIMIT = 20
_DEFAULT_MAX_CHANGES = 6


def _error_payload(action: str, message: str) -> str:
    return json.dumps(
        {
            "ok": False,
            "action": action,
            "error": message,
        },
        ensure_ascii=False,
    )


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ChangelogFormatError("布尔参数必须是 true/false")


def _parse_limit(value: Any) -> int:
    if value is None:
        return _DEFAULT_LIST_LIMIT
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ChangelogFormatError("limit 必须是整数") from exc
    if parsed <= 0:
        raise ChangelogFormatError("limit 必须大于 0")
    return min(parsed, _MAX_LIST_LIMIT)


def _parse_max_changes(value: Any) -> int:
    if value is None:
        return _DEFAULT_MAX_CHANGES
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ChangelogFormatError("max_changes 必须是整数") from exc
    if parsed <= 0:
        raise ChangelogFormatError("max_changes 必须大于 0")
    return parsed


def _resolve_include_flag(
    *,
    raw: Any,
    action: str,
    default_for_detail: bool,
) -> bool:
    parsed = _parse_optional_bool(raw)
    if parsed is not None:
        return parsed
    if action == "list":
        return False
    return default_for_detail


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    _ = context
    action = str(args.get("action") or "latest").strip().lower()
    if action not in {"latest", "list", "show"}:
        return _error_payload(action, "action 只能是 latest、list 或 show")

    try:
        include_summary = _resolve_include_flag(
            raw=args.get("include_summary"),
            action=action,
            default_for_detail=True,
        )
        include_changes = _resolve_include_flag(
            raw=args.get("include_changes"),
            action=action,
            default_for_detail=True,
        )
        max_changes = _parse_max_changes(args.get("max_changes"))

        if action == "latest":
            entry = get_latest_entry()
            payload = {
                "ok": True,
                "action": action,
                "entry": entry_to_dict(
                    entry,
                    include_summary=include_summary,
                    include_changes=include_changes,
                    max_changes=max_changes if include_changes else None,
                ),
            }
        elif action == "show":
            version = str(args.get("version") or "").strip()
            if not version:
                raise ChangelogFormatError("show 动作必须提供 version")
            entry = get_entry(version)
            payload = {
                "ok": True,
                "action": action,
                "entry": entry_to_dict(
                    entry,
                    include_summary=include_summary,
                    include_changes=include_changes,
                    max_changes=max_changes if include_changes else None,
                ),
            }
        else:
            limit = _parse_limit(args.get("limit"))
            entries = list_entries(limit=limit)
            payload = {
                "ok": True,
                "action": action,
                "count": len(entries),
                "items": [
                    entry_to_dict(
                        entry,
                        include_summary=include_summary,
                        include_changes=include_changes,
                        max_changes=max_changes if include_changes else None,
                    )
                    for entry in entries
                ],
            }
    except (FileNotFoundError, ChangelogError) as exc:
        return _error_payload(action, str(exc))

    return json.dumps(payload, ensure_ascii=False)
