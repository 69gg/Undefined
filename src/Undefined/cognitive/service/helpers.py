"""认知服务辅助函数。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from Undefined.utils.coerce import safe_float


def _parse_iso_to_epoch_seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _compose_where(clauses: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _event_base_score(item: dict[str, Any]) -> float:
    # 优先 rerank 分，否则用 1-distance 作为相似度
    rerank_score = item.get("rerank_score")
    if isinstance(rerank_score, (int, float)):
        return max(0.0, float(rerank_score))
    if isinstance(rerank_score, str):
        try:
            return max(0.0, float(rerank_score.strip()))
        except Exception:
            pass
    similarity = 1.0 - safe_float(item.get("distance"), default=1.0)
    if similarity < 0.0:
        return 0.0
    if similarity > 1.0:
        return 1.0
    return similarity


def _event_timestamp_epoch(metadata: Any) -> float:
    if not isinstance(metadata, dict):
        return float("-inf")
    raw_epoch = metadata.get("timestamp_epoch")
    if isinstance(raw_epoch, (int, float)):
        return float(raw_epoch)
    if isinstance(raw_epoch, str):
        try:
            return float(raw_epoch.strip())
        except Exception:
            pass
    for key in ("timestamp_utc", "timestamp_local"):
        parsed = _parse_iso_to_epoch_seconds(metadata.get(key))
        if parsed is not None:
            return float(parsed)
    return float("-inf")


def _event_dedupe_key(item: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    metadata = item.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return (
        str(item.get("document", "")).strip(),
        str(metadata.get("timestamp_epoch", "")).strip(),
        str(metadata.get("timestamp_local", "")).strip(),
        str(metadata.get("group_id", "")).strip(),
        str(metadata.get("sender_id", "")).strip(),
        str(metadata.get("user_id", "")).strip(),
    )


def _resolve_auto_request_type(
    *,
    request_type: str | None,
    group_id: str,
    user_id: str,
    sender_id: str,
) -> str:
    normalized = str(request_type or "").strip().lower()
    if normalized in {"group", "private"}:
        return normalized
    if group_id:
        return "group"
    if sender_id or user_id:
        return "private"
    return ""


def _parse_profile_markdown(markdown: str) -> tuple[dict[str, Any], str] | None:
    text = str(markdown or "")
    if not text.startswith("---"):
        return None
    try:
        import yaml

        parts = text[3:].split("---", 1)
        if len(parts) != 2:
            return None
        frontmatter = yaml.safe_load(parts[0])
        if not isinstance(frontmatter, dict):
            return None
        body = parts[1].lstrip("\n")
        return frontmatter, body
    except Exception:
        return None


def _serialize_profile_markdown(frontmatter: dict[str, Any], body: str) -> str:
    import yaml

    return f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n{body}"


def _normalize_profile_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _current_profile_name(entity_type: str, frontmatter: dict[str, Any]) -> str:
    if entity_type == "user":
        return str(frontmatter.get("nickname") or frontmatter.get("name") or "").strip()
    return str(frontmatter.get("group_name") or frontmatter.get("name") or "").strip()


def _build_profile_vector_payload(
    *,
    entity_type: str,
    entity_id: str,
    effective_name: str,
    tags: list[str],
    summary: str,
) -> tuple[str, dict[str, Any]]:
    profile_doc_lines: list[str] = []
    if entity_type == "user":
        profile_doc_lines.append(f"昵称: {effective_name}")
        profile_doc_lines.append(f"QQ号: {entity_id}")
    else:
        profile_doc_lines.append(f"群名: {effective_name}")
        profile_doc_lines.append(f"群号: {entity_id}")
    if tags:
        profile_doc_lines.append(f"标签: {', '.join(tags)}")
    profile_doc_lines.append(summary)
    profile_doc = "\n".join(line for line in profile_doc_lines if line.strip())

    metadata: dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "name": effective_name,
    }
    if entity_type == "user":
        metadata["nickname"] = effective_name
        metadata["qq"] = entity_id
    else:
        metadata["group_name"] = effective_name
        metadata["group_id"] = entity_id
    return profile_doc, metadata
