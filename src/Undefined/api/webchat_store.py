"""Persistent WebChat conversation storage."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from Undefined.utils import io
from Undefined.utils.paths import (
    HISTORY_DIR,
    WEBCHAT_CONVERSATIONS_DIR,
    WEBCHAT_MIGRATION_MARKER_FILE,
    ensure_dir,
)
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

WEBCHAT_VIRTUAL_USER_ID = 42
WEBCHAT_VIRTUAL_USER_NAME = "system"
DEFAULT_WEBCHAT_CONVERSATION_ID = "legacy-system-42"
_DEFAULT_TITLE = "新对话"
_TEMP_TITLE_CHARS = 18
_MIGRATION_VERSION = 1
_TITLE_STATUS_GENERATED = "generated"
_TITLE_STATUS_MANUAL = "manual"
_TITLE_STATUS_PENDING = "pending"
_TITLE_STATUS_TEMPORARY = "temporary"
_TITLE_STATUS_FAILED = "failed"
_JsonT = TypeVar("_JsonT")


@dataclass(frozen=True)
class WebChatHistoryPage:
    records: list[dict[str, Any]]
    has_more: bool
    next_before: int | None
    total: int


class WebChatHistoryAdapter:
    """Expose one WebChat conversation through MessageHistoryManager-like APIs."""

    def __init__(self, store: WebChatConversationStore, conversation_id: str) -> None:
        self._store = store
        self._conversation_id = conversation_id

    def get_recent(
        self,
        chat_id: str,
        msg_type: str,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        if msg_type != "private" or str(chat_id) != str(WEBCHAT_VIRTUAL_USER_ID):
            return []
        return self._store.get_recent_sync(self._conversation_id, start, end)

    async def add_private_message(
        self,
        user_id: int,
        text_content: str,
        display_name: str = "",
        user_name: str = "",
        message_id: int | None = None,
        attachments: list[dict[str, str]] | None = None,
        webchat: dict[str, Any] | None = None,
    ) -> None:
        _ = message_id
        if int(user_id) != WEBCHAT_VIRTUAL_USER_ID:
            return
        role = "bot" if str(display_name or "").strip().lower() == "bot" else "user"
        await self._store.append_message(
            self._conversation_id,
            role=role,
            text_content=text_content,
            display_name=display_name or user_name or str(user_id),
            user_name=user_name or display_name or str(user_id),
            attachments=attachments,
            webchat=webchat,
        )

    async def flush_pending_saves(self) -> None:
        return None


class WebChatConversationStore:
    """Store WebChat conversations as one JSON file per conversation."""

    def __init__(self) -> None:
        self._global_lock = asyncio.Lock()
        self._migration_lock = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._title_tasks: dict[str, asyncio.Task[None]] = {}
        ensure_dir(WEBCHAT_CONVERSATIONS_DIR)

    def adapter(self, conversation_id: str) -> WebChatHistoryAdapter:
        return WebChatHistoryAdapter(self, conversation_id)

    async def ensure_ready(self, legacy_history_manager: Any | None = None) -> None:
        async with self._global_lock:
            if not self._loaded:
                await self._load_conversations_locked()
                self._loaded = True
        await self._migrate_legacy_once(legacy_history_manager)

    async def ensure_default_conversation(self) -> dict[str, Any]:
        existing = await self.get_conversation(DEFAULT_WEBCHAT_CONVERSATION_ID)
        if existing is not None:
            return existing
        return await self.create_conversation(
            conversation_id=DEFAULT_WEBCHAT_CONVERSATION_ID,
            title=_DEFAULT_TITLE,
            title_source="system",
        )

    async def list_conversations(self) -> list[dict[str, Any]]:
        await self.ensure_ready()
        async with self._global_lock:
            items = [self._conversation_summary(conv) for conv in self._cache.values()]
        return sorted(
            items,
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        await self._ensure_loaded_only()
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._cache.get(conv_id)
            return _copy_json(conv) if conv is not None else None

    async def create_conversation(
        self,
        *,
        conversation_id: str | None = None,
        title: str | None = None,
        title_source: str = "temporary",
    ) -> dict[str, Any]:
        await self._ensure_loaded_only()
        conv_id = _normalize_conversation_id(conversation_id or uuid4().hex)
        now = _now_iso()
        conv: dict[str, Any] = {
            "id": conv_id,
            "title": _sanitize_title(title or _DEFAULT_TITLE) or _DEFAULT_TITLE,
            "title_source": str(title_source or "temporary"),
            "title_status": _TITLE_STATUS_TEMPORARY,
            "created_at": now,
            "updated_at": now,
            "virtual_user_id": WEBCHAT_VIRTUAL_USER_ID,
            "virtual_user_name": WEBCHAT_VIRTUAL_USER_NAME,
            "messages": [],
        }
        async with self._get_lock(conv_id):
            existing = self._cache.get(conv_id)
            if existing is not None:
                return _copy_json(existing)
            self._cache[conv_id] = conv
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 创建会话: conversation_id=%s title_source=%s",
                conv_id,
                conv["title_source"],
            )
            return _copy_json(conv)

    async def rename_conversation(
        self, conversation_id: str, title: str
    ) -> dict[str, Any]:
        conv_id = _normalize_conversation_id(conversation_id)
        clean_title = _sanitize_title(title)
        if not clean_title:
            raise ValueError("title is required")
        async with self._get_lock(conv_id):
            conv = self._require_conversation_locked(conv_id)
            conv["title"] = clean_title
            conv["title_source"] = "manual"
            conv["title_status"] = _TITLE_STATUS_MANUAL
            conv["updated_at"] = _now_iso()
            conv["title_updated_at"] = conv["updated_at"]
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 重命名会话: conversation_id=%s title_len=%s",
                conv_id,
                len(clean_title),
            )
            return _copy_json(conv)

    async def delete_conversation(self, conversation_id: str) -> bool:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            existed = conv_id in self._cache or self._path_for(conv_id).exists()
            self._cache.pop(conv_id, None)
            path = self._path_for(conv_id)
            if path.exists():
                await asyncio.to_thread(path.unlink)
            task = self._title_tasks.pop(conv_id, None)
            if task is not None:
                task.cancel()
            logger.info(
                "[WebChat] 删除会话: conversation_id=%s existed=%s",
                conv_id,
                existed,
            )
            return existed

    async def clear_conversation(self, conversation_id: str) -> int:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._require_conversation_locked(conv_id)
            previous = len(_messages(conv))
            conv["messages"] = []
            conv["updated_at"] = _now_iso()
            conv["title"] = _DEFAULT_TITLE
            conv["title_source"] = "temporary"
            conv["title_status"] = _TITLE_STATUS_TEMPORARY
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 清空会话: conversation_id=%s previous_messages=%s",
                conv_id,
                previous,
            )
            return previous

    async def append_message(
        self,
        conversation_id: str,
        *,
        role: str,
        text_content: str,
        display_name: str,
        user_name: str,
        attachments: list[dict[str, str]] | None = None,
        webchat: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._require_conversation_locked(conv_id)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            normalized_role = "bot" if role == "bot" else "user"
            record: dict[str, Any] = {
                "type": "private",
                "chat_id": str(WEBCHAT_VIRTUAL_USER_ID),
                "chat_name": WEBCHAT_VIRTUAL_USER_NAME,
                "user_id": str(WEBCHAT_VIRTUAL_USER_ID),
                "display_name": display_name or user_name or WEBCHAT_VIRTUAL_USER_NAME,
                "timestamp": timestamp,
                "message": str(text_content or ""),
            }
            if normalized_role == "bot":
                record["display_name"] = "Bot"
                record["chat_name"] = "Bot"
            if attachments:
                record["attachments"] = attachments
            if isinstance(webchat, dict):
                record["webchat"] = webchat
            _messages(conv).append(record)
            conv["updated_at"] = _now_iso()
            if normalized_role == "user":
                self._maybe_apply_temporary_title_locked(conv, record["message"])
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 追加消息: conversation_id=%s role=%s text_len=%s attachments=%s webchat_events=%s total_messages=%s",
                conv_id,
                normalized_role,
                len(record["message"]),
                len(attachments or []),
                len(webchat.get("events", []) if isinstance(webchat, dict) else []),
                len(_messages(conv)),
            )
            return _copy_json(record)

    async def get_history_page(
        self,
        conversation_id: str,
        *,
        limit: int,
        before: int | None,
    ) -> WebChatHistoryPage:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._require_conversation_locked(conv_id)
            history = _messages(conv)
            total = len(history)
            if total == 0 or limit <= 0:
                return WebChatHistoryPage([], False, None, total)
            end = total if before is None else max(0, min(before, total))
            start = max(0, end - limit)
            items = _copy_json(history[start:end])
            has_more = start > 0
            next_before = start if has_more else None
            return WebChatHistoryPage(items, has_more, next_before, total)

    def get_recent_sync(
        self,
        conversation_id: str,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        conv_id = _normalize_conversation_id(conversation_id)
        conv = self._cache.get(conv_id)
        if conv is None:
            return []
        history = _messages(conv)
        total = len(history)
        if total == 0:
            return []
        actual_start = max(0, total - end)
        actual_end = min(total, total - start)
        if actual_start >= actual_end:
            return []
        return _copy_json(history[actual_start:actual_end])

    async def first_question_answer(
        self, conversation_id: str
    ) -> tuple[str, str] | None:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._cache.get(conv_id)
            if conv is None:
                return None
            question = ""
            answer = ""
            for record in _messages(conv):
                role = _record_role(record)
                text = str(record.get("message", "") or "").strip()
                if not text:
                    continue
                if role == "user" and not question:
                    question = text
                    continue
                if question and role == "bot":
                    answer = text
                    break
            if question and answer:
                return question, answer
            return None

    async def mark_title_pending(self, conversation_id: str) -> bool:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._cache.get(conv_id)
            if conv is None:
                return False
            if str(conv.get("title_status") or "") in {
                _TITLE_STATUS_MANUAL,
                _TITLE_STATUS_GENERATED,
            }:
                return False
            first_pair = _first_question_answer_from_conv(conv)
            if first_pair is None:
                return False
            conv["title_status"] = _TITLE_STATUS_PENDING
            conv["title_basis_hash"] = _title_basis_hash(*first_pair)
            conv["title_requested_at"] = _now_iso()
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 标题生成排队: conversation_id=%s question_len=%s answer_len=%s",
                conv_id,
                len(first_pair[0]),
                len(first_pair[1]),
            )
            return True

    async def apply_generated_title(
        self,
        conversation_id: str,
        *,
        title: str,
        basis_hash: str,
    ) -> bool:
        conv_id = _normalize_conversation_id(conversation_id)
        clean_title = _sanitize_title(title)
        if not clean_title:
            return False
        async with self._get_lock(conv_id):
            conv = self._cache.get(conv_id)
            if conv is None:
                return False
            if str(conv.get("title_status") or "") == _TITLE_STATUS_MANUAL:
                return False
            first_pair = _first_question_answer_from_conv(conv)
            if first_pair is None or _title_basis_hash(*first_pair) != basis_hash:
                return False
            conv["title"] = clean_title
            conv["title_source"] = "model"
            conv["title_status"] = _TITLE_STATUS_GENERATED
            conv["title_updated_at"] = _now_iso()
            conv["updated_at"] = conv["title_updated_at"]
            await self._save_conversation_locked(conv)
            logger.info(
                "[WebChat] 应用生成标题: conversation_id=%s title_len=%s",
                conv_id,
                len(clean_title),
            )
            return True

    async def mark_title_failed(self, conversation_id: str, basis_hash: str) -> None:
        conv_id = _normalize_conversation_id(conversation_id)
        async with self._get_lock(conv_id):
            conv = self._cache.get(conv_id)
            if conv is None:
                return
            if str(conv.get("title_status") or "") == _TITLE_STATUS_MANUAL:
                return
            if str(conv.get("title_basis_hash") or "") != basis_hash:
                return
            conv["title_status"] = _TITLE_STATUS_FAILED
            conv["title_failed_at"] = _now_iso()
            await self._save_conversation_locked(conv)
            logger.info("[WebChat] 标题生成失败: conversation_id=%s", conv_id)

    def register_title_task(
        self, conversation_id: str, task: asyncio.Task[None]
    ) -> None:
        conv_id = _normalize_conversation_id(conversation_id)
        previous = self._title_tasks.get(conv_id)
        if previous is not None and not previous.done():
            return
        self._title_tasks[conv_id] = task

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            if self._title_tasks.get(conv_id) is done_task:
                self._title_tasks.pop(conv_id, None)

        task.add_done_callback(_cleanup)

    def title_task_running(self, conversation_id: str) -> bool:
        task = self._title_tasks.get(_normalize_conversation_id(conversation_id))
        return task is not None and not task.done()

    async def _ensure_loaded_only(self) -> None:
        async with self._global_lock:
            if not self._loaded:
                await self._load_conversations_locked()
                self._loaded = True

    async def _load_conversations_locked(self) -> None:
        ensure_dir(WEBCHAT_CONVERSATIONS_DIR)
        self._cache.clear()
        paths = await asyncio.to_thread(
            lambda: sorted(WEBCHAT_CONVERSATIONS_DIR.glob("*.json"))
        )
        for path in paths:
            raw = await io.read_json(path, use_lock=True)
            if not isinstance(raw, dict):
                continue
            conv = _normalize_conversation(raw, path.stem)
            self._cache[str(conv["id"])] = conv
        logger.info(
            "[WebChat] 会话存储加载完成: count=%s dir=%s",
            len(self._cache),
            WEBCHAT_CONVERSATIONS_DIR,
        )

    async def _migrate_legacy_once(self, legacy_history_manager: Any | None) -> None:
        if WEBCHAT_MIGRATION_MARKER_FILE.exists():
            return
        async with self._migration_lock:
            if WEBCHAT_MIGRATION_MARKER_FILE.exists():
                return
            legacy_path = HISTORY_DIR / f"private_{WEBCHAT_VIRTUAL_USER_ID}.json"
            legacy_records = _legacy_records_from_manager(legacy_history_manager)
            if not legacy_records:
                raw = await io.read_json(legacy_path, use_lock=True)
                legacy_records = raw if isinstance(raw, list) else []
            migrated_count = 0
            if legacy_records:
                conv = await self.create_conversation(
                    conversation_id=DEFAULT_WEBCHAT_CONVERSATION_ID,
                    title=_DEFAULT_TITLE,
                    title_source="migration",
                )
                conv_id = str(conv["id"])
                async with self._get_lock(conv_id):
                    cached = self._require_conversation_locked(conv_id)
                    cached["messages"] = [
                        _normalize_history_record(item)
                        for item in legacy_records
                        if isinstance(item, dict)
                    ]
                    migrated_count = len(cached["messages"])
                    first_question = _first_question_from_conv(cached)
                    if first_question:
                        cached["title"] = _temporary_title(first_question)
                        cached["title_source"] = "temporary"
                        cached["title_status"] = _TITLE_STATUS_TEMPORARY
                    cached["legacy_source"] = str(legacy_path)
                    cached["migrated_at"] = _now_iso()
                    cached["updated_at"] = cached["migrated_at"]
                    await self._save_conversation_locked(cached)
            await io.write_json(
                WEBCHAT_MIGRATION_MARKER_FILE,
                {
                    "version": _MIGRATION_VERSION,
                    "migrated_at": _now_iso(),
                    "source": str(legacy_path),
                    "count": migrated_count,
                },
                use_lock=True,
            )
            logger.info(
                "[WebChat] 旧历史迁移完成: migrated_count=%s marker=%s",
                migrated_count,
                WEBCHAT_MIGRATION_MARKER_FILE,
            )

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        lock = self._locks.get(conversation_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[conversation_id] = lock
        return lock

    def _path_for(self, conversation_id: str) -> Path:
        return WEBCHAT_CONVERSATIONS_DIR / f"{conversation_id}.json"

    def _require_conversation_locked(self, conversation_id: str) -> dict[str, Any]:
        conv = self._cache.get(conversation_id)
        if conv is None:
            raise KeyError(conversation_id)
        return conv

    async def _save_conversation_locked(self, conv: dict[str, Any]) -> None:
        normalized = _normalize_conversation(conv, str(conv.get("id") or uuid4().hex))
        self._cache[str(normalized["id"])] = normalized
        await io.write_json(
            self._path_for(str(normalized["id"])), normalized, use_lock=True
        )

    def _conversation_summary(self, conv: dict[str, Any]) -> dict[str, Any]:
        messages = _messages(conv)
        return {
            "id": str(conv.get("id") or ""),
            "title": str(conv.get("title") or _DEFAULT_TITLE),
            "title_source": str(conv.get("title_source") or ""),
            "title_status": str(conv.get("title_status") or ""),
            "created_at": str(conv.get("created_at") or ""),
            "updated_at": str(conv.get("updated_at") or ""),
            "virtual_user_id": WEBCHAT_VIRTUAL_USER_ID,
            "message_count": len(messages),
        }

    def _maybe_apply_temporary_title_locked(
        self, conv: dict[str, Any], first_message: str
    ) -> None:
        status = str(conv.get("title_status") or "")
        if status in {
            _TITLE_STATUS_MANUAL,
            _TITLE_STATUS_GENERATED,
            _TITLE_STATUS_PENDING,
        }:
            return
        title = _temporary_title(first_message)
        if not title:
            return
        conv["title"] = title
        conv["title_source"] = "temporary"
        conv["title_status"] = _TITLE_STATUS_TEMPORARY
        conv["title_updated_at"] = _now_iso()


def _normalize_conversation_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return uuid4().hex
    allowed = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_"})
    return allowed[:80] or uuid4().hex


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _copy_json(value: _JsonT) -> _JsonT:
    import copy

    return copy.deepcopy(value)


def _messages(conv: dict[str, Any]) -> list[dict[str, Any]]:
    messages = conv.get("messages")
    if not isinstance(messages, list):
        messages = []
        conv["messages"] = messages
    return messages


def _normalize_conversation(raw: dict[str, Any], fallback_id: str) -> dict[str, Any]:
    conv = dict(raw)
    conv["id"] = _normalize_conversation_id(str(conv.get("id") or fallback_id))
    conv["title"] = (
        _sanitize_title(conv.get("title") or _DEFAULT_TITLE) or _DEFAULT_TITLE
    )
    conv["title_source"] = str(conv.get("title_source") or "temporary")
    conv["title_status"] = str(conv.get("title_status") or _TITLE_STATUS_TEMPORARY)
    conv["created_at"] = str(conv.get("created_at") or _now_iso())
    conv["updated_at"] = str(conv.get("updated_at") or conv["created_at"])
    conv["virtual_user_id"] = WEBCHAT_VIRTUAL_USER_ID
    conv["virtual_user_name"] = WEBCHAT_VIRTUAL_USER_NAME
    conv["messages"] = [
        _normalize_history_record(item)
        for item in conv.get("messages", [])
        if isinstance(item, dict)
    ]
    return conv


def _normalize_history_record(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)
    item["type"] = "private"
    item["chat_id"] = str(WEBCHAT_VIRTUAL_USER_ID)
    item["user_id"] = str(WEBCHAT_VIRTUAL_USER_ID)
    item["chat_name"] = str(item.get("chat_name") or WEBCHAT_VIRTUAL_USER_NAME)
    item["display_name"] = str(item.get("display_name") or WEBCHAT_VIRTUAL_USER_NAME)
    item["timestamp"] = str(item.get("timestamp") or "")
    item["message"] = str(item.get("message", item.get("content", "")) or "")
    attachments = item.get("attachments")
    item["attachments"] = attachments if isinstance(attachments, list) else []
    return item


def _legacy_records_from_manager(history_manager: Any | None) -> list[dict[str, Any]]:
    if history_manager is None:
        return []
    recent_getter = getattr(history_manager, "get_recent_private", None)
    if callable(recent_getter):
        try:
            records = recent_getter(WEBCHAT_VIRTUAL_USER_ID, 1000000)
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
        except Exception:
            return []
    return []


def _record_role(record: dict[str, Any]) -> str:
    display_name = str(record.get("display_name", "") or "").strip().lower()
    return "bot" if display_name == "bot" else "user"


def _first_question_from_conv(conv: dict[str, Any]) -> str:
    for record in _messages(conv):
        if _record_role(record) != "user":
            continue
        text = str(record.get("message", "") or "").strip()
        if text:
            return text
    return ""


def _first_question_answer_from_conv(conv: dict[str, Any]) -> tuple[str, str] | None:
    question = ""
    for record in _messages(conv):
        text = str(record.get("message", "") or "").strip()
        if not text:
            continue
        role = _record_role(record)
        if role == "user" and not question:
            question = text
            continue
        if question and role == "bot":
            return question, text
    return None


def _temporary_title(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return _DEFAULT_TITLE
    return normalized[:_TEMP_TITLE_CHARS]


def _sanitize_title(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    text = text.strip(" \t\r\n\"'`“”‘’")
    return text[:40]


def _title_basis_hash(question: str, answer: str) -> str:
    basis = f"{question}\n\n{answer}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def webchat_title_basis_hash(question: str, answer: str) -> str:
    return _title_basis_hash(question, answer)


def build_webchat_title_prompt(question: str, answer: str) -> list[dict[str, str]]:
    content = (
        "请为一段 WebChat 对话生成一个简短标题。\n"
        "要求：只返回标题文本；不要引号、编号或前缀；中文不超过 18 个字，英文不超过 6 个词；"
        "标题应概括用户首问和 AI 首答的实际主题。\n\n"
        f"<first_question>{escape_xml_text(question)}</first_question>\n"
        f"<first_answer>{escape_xml_text(answer)}</first_answer>"
    )
    return [{"role": "user", "content": content}]


def _resolve_webchat_title_chat_model(ai: Any) -> Any | None:
    chat_config = getattr(ai, "chat_config", None)
    if chat_config is None:
        runtime_config = getattr(ai, "runtime_config", None)
        chat_config = getattr(runtime_config, "chat_model", None)
    if chat_config is None:
        return None
    selector = getattr(ai, "model_selector", None)
    select_chat_config = getattr(selector, "select_chat_config", None)
    if callable(select_chat_config):
        runtime_config = getattr(ai, "runtime_config", None)
        global_enabled = bool(
            getattr(runtime_config, "model_pool_enabled", True)
            if runtime_config is not None
            else True
        )
        return select_chat_config(
            chat_config,
            group_id=0,
            user_id=WEBCHAT_VIRTUAL_USER_ID,
            global_enabled=global_enabled,
        )
    return chat_config


async def generate_webchat_title(ai: Any, question: str, answer: str) -> str:
    messages = build_webchat_title_prompt(question, answer)
    model_config = _resolve_webchat_title_chat_model(ai)
    logger.info(
        "[WebChat] 生成会话标题: model=%s question_len=%s answer_len=%s",
        getattr(model_config, "model_name", "<none>"),
        len(question),
        len(answer),
    )
    submit = getattr(ai, "submit_background_llm_call", None)
    if callable(submit) and model_config is not None:
        result = await submit(
            model_config=model_config,
            messages=messages,
            tools=None,
            call_type="webchat_title",
        )
        from Undefined.ai.parsing import extract_choices_content

        return _sanitize_title(extract_choices_content(result))
    request_model = getattr(ai, "request_model", None)
    if callable(request_model) and model_config is not None:
        result = await request_model(
            model_config=model_config,
            messages=messages,
            tools=None,
            call_type="webchat_title",
        )
        from Undefined.ai.parsing import extract_choices_content

        return _sanitize_title(extract_choices_content(result))
    generate_title = getattr(ai, "generate_title", None)
    if callable(generate_title):
        logger.info("[WebChat] 会话标题生成回退到 generate_title")
        maybe = generate_title(f"用户首问：{question}\nAI首答：{answer}")
        result_text = await maybe if inspect.isawaitable(maybe) else maybe
        return _sanitize_title(result_text)
    return ""


def format_webchat_message_xml(
    content: str, attachment_xml: str, current_time: str
) -> str:
    return f"""<message sender="{escape_xml_attr(WEBCHAT_VIRTUAL_USER_NAME)}" sender_id="{escape_xml_attr(WEBCHAT_VIRTUAL_USER_ID)}" location="WebUI私聊" time="{escape_xml_attr(current_time)}">
 <content>{escape_xml_text(content)}</content>{attachment_xml}
 </message>"""
