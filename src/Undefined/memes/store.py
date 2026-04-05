from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Callable

from Undefined.memes.models import MemeRecord, MemeSourceRecord, normalize_string_list

logger = logging.getLogger(__name__)


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads_list(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return normalize_string_list(parsed)


def _json_loads_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key or "").strip()
        text = str(raw_value or "").strip()
        if key and text:
            normalized[key] = text
    return normalized


def _escape_like_pattern(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _row_to_record(row: sqlite3.Row) -> MemeRecord:
    return MemeRecord(
        uid=str(row["uid"]),
        content_sha256=str(row["content_sha256"]),
        blob_path=str(row["blob_path"]),
        preview_path=str(row["preview_path"]) if row["preview_path"] else None,
        mime_type=str(row["mime_type"]),
        file_size=int(row["file_size"]),
        width=int(row["width"]) if row["width"] is not None else None,
        height=int(row["height"]) if row["height"] is not None else None,
        is_animated=bool(row["is_animated"]),
        enabled=bool(row["enabled"]),
        pinned=bool(row["pinned"]),
        auto_description=str(row["auto_description"] or ""),
        manual_description=str(row["manual_description"] or ""),
        ocr_text=str(row["ocr_text"] or ""),
        tags=_json_loads_list(row["tags_json"]),
        aliases=_json_loads_list(row["aliases_json"]),
        search_text=str(row["search_text"] or ""),
        use_count=int(row["use_count"] or 0),
        last_used_at=str(row["last_used_at"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        status=str(row["status"] or "ready"),
        segment_data=_json_loads_dict(row["segment_data_json"]),
    )


def _source_row_to_record(row: sqlite3.Row) -> MemeSourceRecord:
    return MemeSourceRecord(
        uid=str(row["uid"] or ""),
        source_type=str(row["source_type"] or ""),
        chat_type=str(row["chat_type"] or ""),
        chat_id=str(row["chat_id"] or ""),
        sender_id=str(row["sender_id"] or ""),
        message_id=str(row["message_id"] or ""),
        attachment_uid=str(row["attachment_uid"] or ""),
        source_url=str(row["source_url"] or ""),
        seen_at=str(row["seen_at"] or ""),
    )


class MemeStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._init_lock = asyncio.Lock()
        self._initialized = False
        self._init_sync()
        self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sync(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memes (
                    uid TEXT PRIMARY KEY,
                    content_sha256 TEXT NOT NULL,
                    blob_path TEXT NOT NULL,
                    preview_path TEXT,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    is_animated INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    auto_description TEXT NOT NULL DEFAULT '',
                    manual_description TEXT NOT NULL DEFAULT '',
                    ocr_text TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    search_text TEXT NOT NULL DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ready',
                    segment_data_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meme_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    chat_type TEXT NOT NULL DEFAULT '',
                    chat_id TEXT NOT NULL DEFAULT '',
                    sender_id TEXT NOT NULL DEFAULT '',
                    message_id TEXT NOT NULL DEFAULT '',
                    attachment_uid TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS meme_fts
                USING fts5(uid UNINDEXED, search_text)
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memes_sha256 ON memes(content_sha256)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memes_status ON memes(status, enabled, pinned)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memes_updated_at ON memes(updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sources_uid ON meme_sources(uid)"
            )
            conn.commit()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._init_sync)
            self._initialized = True

    async def get(self, uid: str) -> MemeRecord | None:
        await self.initialize()

        return await asyncio.to_thread(self.get_sync, uid)

    def get_sync(self, uid: str) -> MemeRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memes WHERE uid = ? LIMIT 1",
                (uid,),
            ).fetchone()
            return _row_to_record(row) if row is not None else None

    async def get_sources(self, uid: str) -> list[MemeSourceRecord]:
        await self.initialize()

        def _run() -> list[MemeSourceRecord]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT uid, source_type, chat_type, chat_id, sender_id,
                           message_id, attachment_uid, source_url, seen_at
                    FROM meme_sources
                    WHERE uid = ?
                    ORDER BY seen_at DESC, id DESC
                    """,
                    (uid,),
                ).fetchall()
                return [_source_row_to_record(row) for row in rows]

        return await asyncio.to_thread(_run)

    async def find_by_sha256(self, content_sha256: str) -> MemeRecord | None:
        await self.initialize()

        def _run() -> MemeRecord | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memes WHERE content_sha256 = ? LIMIT 1",
                    (content_sha256,),
                ).fetchone()
                return _row_to_record(row) if row is not None else None

        return await asyncio.to_thread(_run)

    async def upsert_record(self, record: MemeRecord) -> MemeRecord:
        await self.initialize()

        def _run() -> MemeRecord:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO memes (
                        uid, content_sha256, blob_path, preview_path, mime_type,
                        file_size, width, height, is_animated, enabled, pinned,
                        auto_description, manual_description, ocr_text, tags_json,
                        aliases_json, search_text, use_count, last_used_at,
                        created_at, updated_at, status, segment_data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(uid) DO UPDATE SET
                        content_sha256 = excluded.content_sha256,
                        blob_path = excluded.blob_path,
                        preview_path = excluded.preview_path,
                        mime_type = excluded.mime_type,
                        file_size = excluded.file_size,
                        width = excluded.width,
                        height = excluded.height,
                        is_animated = excluded.is_animated,
                        enabled = excluded.enabled,
                        pinned = excluded.pinned,
                        auto_description = excluded.auto_description,
                        manual_description = excluded.manual_description,
                        ocr_text = excluded.ocr_text,
                        tags_json = excluded.tags_json,
                        aliases_json = excluded.aliases_json,
                        search_text = excluded.search_text,
                        use_count = excluded.use_count,
                        last_used_at = excluded.last_used_at,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at,
                        status = excluded.status,
                        segment_data_json = excluded.segment_data_json
                    """,
                    (
                        record.uid,
                        record.content_sha256,
                        record.blob_path,
                        record.preview_path,
                        record.mime_type,
                        record.file_size,
                        record.width,
                        record.height,
                        _bool_to_int(record.is_animated),
                        _bool_to_int(record.enabled),
                        _bool_to_int(record.pinned),
                        record.auto_description,
                        record.manual_description,
                        record.ocr_text,
                        _json_dumps(record.tags),
                        _json_dumps(record.aliases),
                        record.search_text,
                        record.use_count,
                        record.last_used_at,
                        record.created_at,
                        record.updated_at,
                        record.status,
                        _json_dumps(record.segment_data),
                    ),
                )
                conn.execute("DELETE FROM meme_fts WHERE uid = ?", (record.uid,))
                conn.execute(
                    "INSERT INTO meme_fts(uid, search_text) VALUES (?, ?)",
                    (record.uid, record.search_text),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM memes WHERE uid = ? LIMIT 1",
                    (record.uid,),
                ).fetchone()
                if row is None:
                    raise RuntimeError(f"upsert meme failed: {record.uid}")
                return _row_to_record(row)

        return await asyncio.to_thread(_run)

    async def add_source(self, source: MemeSourceRecord) -> None:
        await self.initialize()

        def _run() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO meme_sources (
                        uid, source_type, chat_type, chat_id, sender_id,
                        message_id, attachment_uid, source_url, seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source.uid,
                        source.source_type,
                        source.chat_type,
                        source.chat_id,
                        source.sender_id,
                        source.message_id,
                        source.attachment_uid,
                        source.source_url,
                        source.seen_at,
                    ),
                )
                conn.commit()

        await asyncio.to_thread(_run)

    def _fts_expression(self, query: str) -> str:
        expressions: list[str] = []
        for raw_token in str(query or "").split():
            token = raw_token.replace("\x00", " ").strip().strip('"')
            if not token:
                continue
            escaped = token.replace('"', '""')
            expressions.append(f'"{escaped}"')
            if len(expressions) >= 8:
                break
        return " ".join(expressions)

    async def search_keyword(
        self,
        query: str,
        *,
        limit: int,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        await self.initialize()
        raw_query = str(query or "").strip()
        if not raw_query:
            return []
        normalized = raw_query.lower()
        escaped = normalized.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        like_query = f"%{escaped}%"
        fts_expr = self._fts_expression(raw_query)

        def _run() -> list[dict[str, Any]]:
            found: dict[str, dict[str, Any]] = {}
            with self._connect() as conn:
                if fts_expr:
                    rows = conn.execute(
                        """
                        SELECT m.*, bm25(meme_fts) AS fts_rank
                        FROM meme_fts
                        JOIN memes AS m ON m.uid = meme_fts.uid
                        WHERE meme_fts MATCH ?
                          AND m.status = 'ready'
                          AND (? OR m.enabled = 1)
                        ORDER BY fts_rank ASC, m.use_count DESC, m.updated_at DESC
                        LIMIT ?
                        """,
                        (fts_expr, _bool_to_int(include_disabled), limit),
                    ).fetchall()
                    for row in rows:
                        record = _row_to_record(row)
                        fts_rank = (
                            float(row["fts_rank"])
                            if row["fts_rank"] is not None
                            else 0.0
                        )
                        keyword_score = 1.0 / (1.0 + abs(fts_rank))
                        found[record.uid] = {
                            "record": record,
                            "keyword_score": keyword_score,
                        }

                rows = conn.execute(
                    """
                    SELECT *
                    FROM memes
                    WHERE status = 'ready'
                      AND (? OR enabled = 1)
                      AND (
                        lower(search_text) LIKE ? ESCAPE '!'
                        OR lower(uid) LIKE ? ESCAPE '!'
                      )
                    ORDER BY pinned DESC, use_count DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (
                        _bool_to_int(include_disabled),
                        like_query,
                        like_query,
                        limit,
                    ),
                ).fetchall()
                for row in rows:
                    record = _row_to_record(row)
                    base_score = 0.6
                    if normalized in record.description.lower():
                        base_score = 0.95
                    elif normalized in record.search_text.lower():
                        base_score = 0.8
                    current = found.get(record.uid)
                    if current is None or base_score > float(
                        current.get("keyword_score", 0.0)
                    ):
                        found[record.uid] = {
                            "record": record,
                            "keyword_score": base_score,
                        }

            ranked = sorted(
                found.values(),
                key=lambda item: (
                    float(item.get("keyword_score", 0.0)),
                    item["record"].pinned,
                    item["record"].use_count,
                    item["record"].updated_at,
                ),
                reverse=True,
            )
            return ranked[:limit]

        return await asyncio.to_thread(_run)

    async def list_memes(
        self,
        *,
        query: str = "",
        enabled: bool | None = None,
        animated: bool | None = None,
        pinned: bool | None = None,
        sort: str = "updated_at",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[MemeRecord], int]:
        await self.initialize()
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(200, int(page_size)))
        offset = (safe_page - 1) * safe_page_size
        order_map = {
            "created_at": "created_at DESC",
            "use_count": "use_count DESC, updated_at DESC",
            "updated_at": "updated_at DESC",
        }
        order_by = order_map.get(sort, order_map["updated_at"])
        normalized_query = str(query or "").strip().lower()
        like_query = f"%{_escape_like_pattern(normalized_query)}%"

        def _run() -> tuple[list[MemeRecord], int]:
            clauses = ["status = 'ready'"]
            params: list[Any] = []
            if enabled is not None:
                clauses.append("enabled = ?")
                params.append(_bool_to_int(enabled))
            if animated is not None:
                clauses.append("is_animated = ?")
                params.append(_bool_to_int(animated))
            if pinned is not None:
                clauses.append("pinned = ?")
                params.append(_bool_to_int(pinned))
            if normalized_query:
                clauses.append(
                    "(lower(search_text) LIKE ? ESCAPE '!' OR lower(uid) LIKE ? ESCAPE '!')"
                )
                params.extend([like_query, like_query])
            where_sql = " AND ".join(clauses)

            with self._connect() as conn:
                total = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM memes WHERE {where_sql}",
                        tuple(params),
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM memes
                    WHERE {where_sql}
                    ORDER BY pinned DESC, {order_by}
                    LIMIT ? OFFSET ?
                    """,
                    tuple(params + [safe_page_size, offset]),
                ).fetchall()
                return ([_row_to_record(row) for row in rows], total)

        return await asyncio.to_thread(_run)

    async def update_fields(
        self, uid: str, values: dict[str, Any]
    ) -> MemeRecord | None:
        await self.initialize()
        if not values:
            return await self.get(uid)

        def _run() -> MemeRecord | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memes WHERE uid = ? LIMIT 1",
                    (uid,),
                ).fetchone()
                if row is None:
                    return None
                allowed_columns: dict[str, Callable[[Any], Any]] = {
                    "enabled": lambda value: _bool_to_int(bool(value)),
                    "pinned": lambda value: _bool_to_int(bool(value)),
                    "manual_description": lambda value: str(value or ""),
                    "auto_description": lambda value: str(value or ""),
                    "ocr_text": lambda value: str(value or ""),
                    "search_text": lambda value: str(value or ""),
                    "updated_at": lambda value: str(value or ""),
                    "use_count": lambda value: int(value or 0),
                    "last_used_at": lambda value: str(value or ""),
                    "status": lambda value: str(value or "ready"),
                    "tags_json": lambda value: _json_dumps(
                        normalize_string_list(value)
                    ),
                    "aliases_json": lambda value: _json_dumps(
                        normalize_string_list(value)
                    ),
                }
                assignments: list[str] = []
                params: list[Any] = []
                for key, raw_value in values.items():
                    normalizer = allowed_columns.get(key)
                    if normalizer is None:
                        continue
                    assignments.append(f"{key} = ?")
                    params.append(normalizer(raw_value))
                if not assignments:
                    return _row_to_record(row)
                params.append(uid)
                conn.execute(
                    f"UPDATE memes SET {', '.join(assignments)} WHERE uid = ?",
                    tuple(params),
                )
                search_text_row = conn.execute(
                    "SELECT search_text FROM memes WHERE uid = ? LIMIT 1",
                    (uid,),
                ).fetchone()
                if search_text_row is not None:
                    conn.execute("DELETE FROM meme_fts WHERE uid = ?", (uid,))
                    conn.execute(
                        "INSERT INTO meme_fts(uid, search_text) VALUES (?, ?)",
                        (uid, str(search_text_row["search_text"] or "")),
                    )
                conn.commit()
                updated = conn.execute(
                    "SELECT * FROM memes WHERE uid = ? LIMIT 1",
                    (uid,),
                ).fetchone()
                return _row_to_record(updated) if updated is not None else None

        return await asyncio.to_thread(_run)

    async def increment_use(self, uid: str, used_at: str) -> MemeRecord | None:
        current = await self.get(uid)
        if current is None:
            return None
        return await self.update_fields(
            uid,
            {
                "use_count": current.use_count + 1,
                "last_used_at": used_at,
                "updated_at": used_at,
            },
        )

    async def delete(self, uid: str) -> MemeRecord | None:
        await self.initialize()

        def _run() -> MemeRecord | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memes WHERE uid = ? LIMIT 1",
                    (uid,),
                ).fetchone()
                if row is None:
                    return None
                record = _row_to_record(row)
                conn.execute("DELETE FROM memes WHERE uid = ?", (uid,))
                conn.execute("DELETE FROM meme_sources WHERE uid = ?", (uid,))
                conn.execute("DELETE FROM meme_fts WHERE uid = ?", (uid,))
                conn.commit()
                return record

        return await asyncio.to_thread(_run)

    async def stats(self) -> dict[str, Any]:
        await self.initialize()

        def _run() -> dict[str, Any]:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_count,
                        COALESCE(SUM(file_size), 0) AS total_bytes,
                        SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) AS enabled_count,
                        SUM(CASE WHEN is_animated = 1 THEN 1 ELSE 0 END) AS animated_count,
                        SUM(CASE WHEN pinned = 1 THEN 1 ELSE 0 END) AS pinned_count
                    FROM memes
                    WHERE status = 'ready'
                    """
                ).fetchone()
                return {
                    "total_count": int(row["total_count"] or 0),
                    "total_bytes": int(row["total_bytes"] or 0),
                    "enabled_count": int(row["enabled_count"] or 0),
                    "animated_count": int(row["animated_count"] or 0),
                    "pinned_count": int(row["pinned_count"] or 0),
                }

        return await asyncio.to_thread(_run)

    async def list_prune_candidates(self) -> list[MemeRecord]:
        await self.initialize()

        def _run() -> list[MemeRecord]:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memes
                    ORDER BY
                        CASE WHEN status = 'ready' THEN 1 ELSE 0 END ASC,
                        pinned ASC,
                        enabled DESC,
                        use_count ASC,
                        CASE WHEN last_used_at = '' THEN created_at ELSE last_used_at END ASC,
                        updated_at ASC
                    """
                ).fetchall()
                return [_row_to_record(row) for row in rows]

        return await asyncio.to_thread(_run)
