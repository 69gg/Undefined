"""历史记录管理"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Final

from Undefined.utils.coerce import safe_int
from Undefined.utils.message_reply import ReplyContext

logger = logging.getLogger(__name__)

# 历史记录文件路径
HISTORY_DIR = os.path.join("data", "history")
_HISTORY_TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
# 旧记录只有秒级时间，数字 msg_id 插值也可能有几十秒偏差。
_REFERENCE_MATCH_TOLERANCE_MS: Final[int] = 90_000


def _extract_id_from_history_filename(path: str, prefix: str) -> str:
    filename = os.path.basename(path)
    if filename.startswith(prefix) and filename.endswith(".json"):
        return filename[len(prefix) : -5]
    return ""


def _record_transport(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("transport")
    return raw if isinstance(raw, dict) else {}


def _record_matches_route(
    record: dict[str, Any],
    *,
    channel: str | None,
    address: str | None,
) -> bool:
    transport = _record_transport(record)
    if channel and str(transport.get("channel", "")) != channel:
        return False
    return not address or str(transport.get("address", "")) == address


def _record_local_timestamp_ms(record: dict[str, Any]) -> tuple[int, bool] | None:
    transport = _record_transport(record)
    sent_at_ms = safe_int(transport.get("sent_at_ms"))
    if sent_at_ms is not None and sent_at_ms > 0:
        return sent_at_ms, True
    created_at_ms = safe_int(transport.get("created_at_ms"))
    if created_at_ms is not None and created_at_ms > 0:
        return created_at_ms, True
    timestamp = str(record.get("timestamp", "") or "").strip()
    if not timestamp:
        return None
    try:
        parsed = datetime.strptime(timestamp, _HISTORY_TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000), False


def _interpolate_reference_timestamp_ms(
    history: list[dict[str, Any]],
    reference_message_id: int,
    *,
    current_message_id: int,
    current_received_at_ms: int,
    channel: str | None,
    address: str | None,
) -> int | None:
    anchors: dict[int, int] = {current_message_id: current_received_at_ms}
    for record in history:
        if not _record_matches_route(record, channel=channel, address=address):
            continue
        message_id = safe_int(record.get("message_id"))
        timestamp = _record_local_timestamp_ms(record)
        if message_id is None or message_id <= 0 or timestamp is None:
            continue
        anchors[message_id] = timestamp[0]

    lower = max(
        (item for item in anchors if item <= reference_message_id), default=None
    )
    upper = min(
        (item for item in anchors if item >= reference_message_id), default=None
    )
    if lower is None or upper is None:
        return None
    if lower == upper:
        return anchors[lower]
    lower_timestamp = anchors[lower]
    upper_timestamp = anchors[upper]
    if upper_timestamp < lower_timestamp:
        return None
    return lower_timestamp + (
        (reference_message_id - lower)
        * (upper_timestamp - lower_timestamp)
        // (upper - lower)
    )


class MessageHistoryManager:
    """消息历史管理器（异步，Lazy Load）"""

    _max_records: int = 10000

    def __init__(self, max_records: int = 10000) -> None:
        self._max_records = max_records
        self._message_history: dict[str, list[dict[str, Any]]] = {}
        self._private_message_history: dict[str, list[dict[str, Any]]] = {}
        self._group_locks: dict[str, asyncio.Lock] = {}
        self._private_locks: dict[str, asyncio.Lock] = {}
        self._pending_history_saves: dict[str, list[dict[str, Any]]] = {}
        self._history_save_tasks: dict[str, asyncio.Task[None]] = {}

        # Lazy Load 初始化标志
        self._initialized = asyncio.Event()
        self._init_task: asyncio.Task[None] | None = None

        # 确保目录存在（同步操作，很快）
        os.makedirs(HISTORY_DIR, exist_ok=True)

        # 启动后台异步加载任务
        self._init_task = asyncio.create_task(self._lazy_init())

    def _get_group_lock(self, group_id: str) -> asyncio.Lock:
        lock = self._group_locks.get(group_id)
        if lock is None:
            lock = asyncio.Lock()
            self._group_locks[group_id] = lock
        return lock

    def _get_private_lock(self, user_id: str) -> asyncio.Lock:
        lock = self._private_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._private_locks[user_id] = lock
        return lock

    def _ensure_save_state(self) -> None:
        if not hasattr(self, "_pending_history_saves"):
            self._pending_history_saves = {}
        if not hasattr(self, "_history_save_tasks"):
            self._history_save_tasks = {}

    def _snapshot_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._max_records > 0 and len(history) > self._max_records:
            return list(history[-self._max_records :])
        return list(history)

    def _queue_history_save(self, history: list[dict[str, Any]], path: str) -> None:
        self._ensure_save_state()
        self._pending_history_saves[path] = self._snapshot_history(history)
        task = self._history_save_tasks.get(path)
        if task is None or task.done():
            self._history_save_tasks[path] = asyncio.create_task(
                self._drain_history_save(path),
                name=f"history_save:{path}",
            )

    async def _drain_history_save(self, path: str) -> None:
        failed = False
        try:
            while True:
                self._ensure_save_state()
                history = self._pending_history_saves.pop(path, None)
                if history is None:
                    break
                try:
                    await self._save_history_to_file(history, path)
                except Exception:
                    logger.exception("[历史记录错误] 保存历史失败: path=%s", path)
                    self._pending_history_saves.setdefault(path, history)
                    failed = True
                    break
        finally:
            self._ensure_save_state()
            current_task = asyncio.current_task()
            if self._history_save_tasks.get(path) is current_task:
                self._history_save_tasks.pop(path, None)
            if not failed and path in self._pending_history_saves:
                self._history_save_tasks[path] = asyncio.create_task(
                    self._drain_history_save(path),
                    name=f"history_save:{path}",
                )

    async def flush_pending_saves(self) -> None:
        self._ensure_save_state()
        while self._history_save_tasks:
            tasks = list(self._history_save_tasks.values())
            await asyncio.gather(*tasks, return_exceptions=True)
            self._ensure_save_state()

    async def _lazy_init(self) -> None:
        """后台异步加载所有历史记录"""
        try:
            logger.debug("[历史记录] 开始后台加载历史记录...")
            await self._load_all_histories()
            logger.info("[历史记录] 后台加载完成")
        except Exception as e:
            logger.error(f"[历史记录错误] 后台加载失败: {e}")
        finally:
            self._initialized.set()

    async def _ensure_initialized(self) -> None:
        """确保历史记录已加载（所有公共方法调用前必须调用）"""
        await self._initialized.wait()

    def _get_group_history_path(self, group_id: int) -> str:
        """获取群消息历史文件路径"""
        return os.path.join(HISTORY_DIR, f"group_{group_id}.json")

    def _get_private_history_path(self, user_id: int) -> str:
        """获取私聊消息历史文件路径"""
        return os.path.join(HISTORY_DIR, f"private_{user_id}.json")

    async def _save_history_to_file(
        self, history: list[dict[str, Any]], path: str
    ) -> None:
        """异步保存历史记录到文件"""
        from Undefined.utils import io

        try:
            if self._max_records > 0:
                truncated_history = (
                    history[-self._max_records :]
                    if len(history) > self._max_records
                    else history
                )
                truncated = len(history) > self._max_records
            else:
                truncated_history = history
                truncated = False

            logger.debug(
                f"[历史记录] 准备保存: path={path}, total={len(history)}, truncated={truncated}"
            )

            await io.write_json(path, truncated_history, use_lock=True)

            logger.debug(f"[历史记录] 保存成功: path={path}")
        except Exception as e:
            logger.error(f"[历史记录错误] 保存历史记录失败 {path}: {e}")
            raise

    async def _load_history_from_file(self, path: str) -> list[dict[str, Any]]:
        """异步从文件加载历史记录"""
        from Undefined.utils import io

        try:
            history = await io.read_json(path, use_lock=False)

            if history is None:
                logger.debug(f"[历史记录] 文件不存在: path={path}")
                return []

            if isinstance(history, list):
                group_id_from_path = _extract_id_from_history_filename(path, "group_")
                private_id_from_path = _extract_id_from_history_filename(
                    path, "private_"
                )
                is_group_path = bool(group_id_from_path)

                normalized_history: list[dict[str, Any]] = []
                # 兼容旧格式：补充缺失字段，避免后续上下文注入出现空 sender/chat
                for msg in history:
                    if not isinstance(msg, dict):
                        continue

                    msg_type = str(msg.get("type", "")).strip().lower()
                    if msg_type not in {"group", "private"}:
                        msg_type = "group" if is_group_path else "private"
                        msg["type"] = msg_type

                    chat_id_val = str(msg.get("chat_id", "")).strip()
                    if not chat_id_val:
                        if msg_type == "group":
                            chat_id_val = group_id_from_path
                        else:
                            chat_id_val = private_id_from_path
                        msg["chat_id"] = chat_id_val

                    user_id_val = str(msg.get("user_id", "")).strip()
                    if not user_id_val:
                        fallback_user_id = str(msg.get("sender_id", "")).strip()
                        if not fallback_user_id and msg_type == "private":
                            fallback_user_id = chat_id_val or private_id_from_path
                        msg["user_id"] = fallback_user_id

                    if not str(msg.get("display_name", "")).strip():
                        fallback_display = (
                            msg.get("sender_name")
                            or msg.get("nickname")
                            or msg.get("user_id")
                            or "未知用户"
                        )
                        msg["display_name"] = str(fallback_display)

                    if not str(msg.get("chat_name", "")).strip():
                        if msg_type == "group":
                            group_chat_id = chat_id_val or group_id_from_path
                            msg["chat_name"] = f"群{group_chat_id}"
                        else:
                            private_chat_id = chat_id_val or private_id_from_path
                            msg["chat_name"] = f"QQ用户{private_chat_id}"

                    if "timestamp" not in msg or msg.get("timestamp") is None:
                        msg["timestamp"] = ""
                    if "message" not in msg or msg.get("message") is None:
                        msg["message"] = str(msg.get("content", ""))
                    attachments = msg.get("attachments")
                    if not isinstance(attachments, list):
                        msg["attachments"] = []
                    else:
                        normalized_attachments: list[dict[str, str]] = []
                        for item in attachments:
                            if not isinstance(item, dict):
                                continue
                            uid = str(item.get("uid", "") or "").strip()
                            if not uid:
                                continue
                            normalized_attachments.append(
                                {
                                    "uid": uid,
                                    "kind": str(
                                        item.get("kind")
                                        or item.get("media_type")
                                        or "file"
                                    ),
                                    "media_type": str(
                                        item.get("media_type")
                                        or item.get("kind")
                                        or "file"
                                    ),
                                    "display_name": str(
                                        item.get("display_name", "") or ""
                                    ),
                                    "source_kind": str(
                                        item.get("source_kind", "") or ""
                                    ),
                                    "semantic_kind": str(
                                        item.get("semantic_kind", "") or ""
                                    ),
                                    "description": str(
                                        item.get("description", "") or ""
                                    ),
                                }
                            )
                        msg["attachments"] = normalized_attachments

                    reply_context = ReplyContext.from_mapping(msg.get("reply_context"))
                    if reply_context is None:
                        msg.pop("reply_context", None)
                    else:
                        msg["reply_context"] = reply_context.to_dict()

                    normalized_history.append(msg)

                if self._max_records > 0:
                    return (
                        normalized_history[-self._max_records :]
                        if len(normalized_history) > self._max_records
                        else normalized_history
                    )
                return normalized_history
        except Exception as e:
            logger.error(f"加载历史记录失败 {path}: {e}")

        return []

    async def _load_all_histories(self) -> None:
        """启动时异步加载所有历史记录（并发优化）"""
        if not os.path.exists(HISTORY_DIR):
            logger.info("历史消息目录不存在，跳过加载")
            return

        # 异步列出文件
        def list_files() -> list[str]:
            return os.listdir(HISTORY_DIR)

        filenames = await asyncio.to_thread(list_files)

        # 并发加载所有历史文件
        group_tasks = []
        group_ids = []
        private_tasks = []
        private_ids = []

        for filename in filenames:
            if filename.startswith("group_") and filename.endswith(".json"):
                try:
                    group_id_str = filename[6:-5]  # 提取群号
                    path = os.path.join(HISTORY_DIR, filename)
                    group_tasks.append(self._load_history_from_file(path))
                    group_ids.append(group_id_str)
                except Exception as e:
                    logger.error(f"[历史记录错误] 准备加载群历史失败 {filename}: {e}")

            elif filename.startswith("private_") and filename.endswith(".json"):
                try:
                    user_id_str = filename[8:-5]  # 提取用户ID
                    path = os.path.join(HISTORY_DIR, filename)
                    private_tasks.append(self._load_history_from_file(path))
                    private_ids.append(user_id_str)
                except Exception as e:
                    logger.error(f"[历史记录错误] 准备加载私聊历史失败 {filename}: {e}")

        # 并发加载群聊历史
        if group_tasks:
            group_results = await asyncio.gather(*group_tasks, return_exceptions=True)
            for i, result in enumerate(group_results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[历史记录错误] 加载群 {group_ids[i]} 历史失败: {result}"
                    )
                elif isinstance(result, list):
                    self._message_history[group_ids[i]] = result
                    logger.debug(
                        f"[历史记录] 已加载群 {group_ids[i]} 历史消息: {len(result)} 条"
                    )

        logger.info(
            f"[历史记录] 共加载了 {len(self._message_history)} 个群聊的历史记录"
        )

        # 并发加载私聊历史
        if private_tasks:
            private_results = await asyncio.gather(
                *private_tasks, return_exceptions=True
            )
            for i, result in enumerate(private_results):
                if isinstance(result, Exception):
                    logger.error(
                        f"[历史记录错误] 加载私聊 {private_ids[i]} 历史失败: {result}"
                    )
                elif isinstance(result, list):
                    self._private_message_history[private_ids[i]] = result
                    logger.debug(
                        f"[历史记录] 已加载私聊 {private_ids[i]} 历史消息: {len(result)} 条"
                    )

        logger.info(
            f"[历史记录] 共加载了 {len(self._private_message_history)} 个私聊会话的历史记录"
        )

    async def add_group_message(
        self,
        group_id: int,
        sender_id: int,
        text_content: str,
        sender_card: str = "",
        sender_nickname: str = "",
        group_name: str = "",
        role: str = "member",
        title: str = "",
        level: str = "",
        message_id: int | str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> None:
        """异步保存群消息到历史记录"""
        await self._ensure_initialized()

        group_id_str = str(group_id)
        sender_id_str = str(sender_id)

        async with self._get_group_lock(group_id_str):
            if group_id_str not in self._message_history:
                self._message_history[group_id_str] = []

            display_name = sender_card or sender_nickname or sender_id_str

            current_count = len(self._message_history[group_id_str])
            logger.debug(
                f"[历史记录] 追加群消息: group={group_id}, current_count={current_count}"
            )

            record: dict[str, Any] = {
                "type": "group",
                "chat_id": group_id_str,
                "chat_name": group_name or f"群{group_id_str}",
                "user_id": sender_id_str,
                "display_name": display_name,
                "role": role,
                "title": title,
                "level": level,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text_content,
            }
            if message_id is not None:
                record["message_id"] = message_id
            if attachments:
                record["attachments"] = attachments

            self._message_history[group_id_str].append(record)

            if (
                self._max_records > 0
                and len(self._message_history[group_id_str]) > self._max_records
            ):
                self._message_history[group_id_str] = self._message_history[
                    group_id_str
                ][-self._max_records :]

            self._queue_history_save(
                self._message_history[group_id_str],
                self._get_group_history_path(group_id),
            )

    async def add_private_message(
        self,
        user_id: int,
        text_content: str,
        display_name: str = "",
        user_name: str = "",
        message_id: int | str | None = None,
        attachments: list[dict[str, str]] | None = None,
        webchat: dict[str, Any] | None = None,
        transport: dict[str, Any] | None = None,
        reply_context: ReplyContext | None = None,
    ) -> None:
        """异步保存私聊消息到历史记录"""
        await self._ensure_initialized()

        user_id_str = str(user_id)

        async with self._get_private_lock(user_id_str):
            if user_id_str not in self._private_message_history:
                self._private_message_history[user_id_str] = []

            current_count = len(self._private_message_history[user_id_str])
            logger.debug(
                f"[历史记录] 追加私聊消息: user={user_id}, current_count={current_count}"
            )

            record: dict[str, Any] = {
                "type": "private",
                "chat_id": user_id_str,
                "chat_name": user_name or f"QQ用户{user_id_str}",
                "user_id": user_id_str,
                "display_name": display_name or user_name or user_id_str,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text_content,
            }
            if message_id is not None:
                record["message_id"] = message_id
            if attachments:
                record["attachments"] = attachments
            if isinstance(webchat, dict):
                record["webchat"] = webchat
            if isinstance(transport, dict):
                record["transport"] = dict(transport)
            if reply_context is not None and not reply_context.is_empty:
                record["reply_context"] = reply_context.to_dict()

            self._private_message_history[user_id_str].append(record)

            if (
                self._max_records > 0
                and len(self._private_message_history[user_id_str]) > self._max_records
            ):
                self._private_message_history[user_id_str] = (
                    self._private_message_history[user_id_str][-self._max_records :]
                )

            self._queue_history_save(
                self._private_message_history[user_id_str],
                self._get_private_history_path(user_id),
            )

    def get_recent(
        self,
        chat_id: str,
        msg_type: str,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        """获取指定的历史消息"""
        if msg_type == "group":
            if chat_id not in self._message_history:
                return []
            history = self._message_history[chat_id]
        elif msg_type == "private":
            if chat_id not in self._private_message_history:
                return []
            history = self._private_message_history[chat_id]
        else:
            return []

        total = len(history)
        if total == 0:
            return []

        actual_start = total - end
        actual_end = total - start

        if actual_start < 0:
            actual_start = 0
        if actual_end > total:
            actual_end = total
        if actual_start >= actual_end:
            return []

        return history[actual_start:actual_end]

    def get_recent_private(self, user_id: int, count: int) -> list[dict[str, Any]]:
        """获取最近的私聊消息"""
        user_id_str = str(user_id)
        if user_id_str not in self._private_message_history:
            return []
        return self._private_message_history[user_id_str][-count:] if count > 0 else []

    async def find_private_message_by_id(
        self,
        user_id: int,
        message_id: int | str,
        *,
        channel: str | None = None,
        address: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a private record by transport-visible ID within an optional route."""

        await self._ensure_initialized()
        user_id_str = str(user_id)
        expected_id = str(message_id).strip()
        if not expected_id:
            return None
        async with self._get_private_lock(user_id_str):
            history = self._private_message_history.get(user_id_str, [])
            for record in reversed(history):
                transport_raw = record.get("transport")
                transport = transport_raw if isinstance(transport_raw, dict) else {}
                if channel and str(transport.get("channel", "")) != channel:
                    continue
                if address and str(transport.get("address", "")) != address:
                    continue
                candidate_ids = {str(record.get("message_id", "") or "").strip()}
                raw_ids = transport.get("message_ids")
                if isinstance(raw_ids, list):
                    candidate_ids.update(str(item).strip() for item in raw_ids)
                if expected_id in candidate_ids:
                    return dict(record)
        return None

    async def find_private_bot_messages_for_reference(
        self,
        user_id: int,
        reference_message_id: int | str,
        *,
        current_message_id: int | str | None,
        current_received_at_ms: int,
        reference_age_ms: int | None = None,
        channel: str | None = None,
        address: str | None = None,
    ) -> list[dict[str, Any]]:
        """按同路由发送时间恢复无法用服务端 ID 直接关联的机器人消息。"""

        await self._ensure_initialized()
        user_id_str = str(user_id)
        reference_id = safe_int(reference_message_id)
        if reference_id is None or reference_id <= 0:
            return []
        async with self._get_private_lock(user_id_str):
            history = self._private_message_history.get(user_id_str, [])
            estimated_at_ms: int | None = None
            if reference_age_ms is not None and reference_age_ms > 0:
                estimated_at_ms = current_received_at_ms - reference_age_ms
            else:
                current_id = safe_int(current_message_id)
                if current_id is not None and current_id > reference_id:
                    estimated_at_ms = _interpolate_reference_timestamp_ms(
                        history,
                        reference_id,
                        current_message_id=current_id,
                        current_received_at_ms=current_received_at_ms,
                        channel=channel,
                        address=address,
                    )
            if estimated_at_ms is None:
                return []

            candidates: list[tuple[int, bool, dict[str, Any]]] = []
            for record in history:
                transport = _record_transport(record)
                direction = str(transport.get("direction", "") or "")
                if direction and direction != "outbound":
                    continue
                if not direction and str(record.get("display_name", "") or "") != "Bot":
                    continue
                if not _record_matches_route(
                    record,
                    channel=channel,
                    address=address,
                ):
                    continue
                timestamp = _record_local_timestamp_ms(record)
                if timestamp is not None:
                    candidates.append((timestamp[0], timestamp[1], record))
            if not candidates:
                return []

            nearest = min(candidates, key=lambda item: abs(item[0] - estimated_at_ms))
            if abs(nearest[0] - estimated_at_ms) > _REFERENCE_MATCH_TOLERANCE_MS:
                return []
            if nearest[1]:
                return [dict(nearest[2])]
            return [
                dict(record)
                for timestamp_ms, precise, record in candidates
                if not precise and timestamp_ms == nearest[0]
            ]

    def get_private_page(
        self,
        user_id: int,
        *,
        limit: int,
        before: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool, int | None, int]:
        """按时间倒序游标分页读取私聊历史，返回结果保持正序。

        ``before`` 是完整历史数组里的结束下标（exclusive）。不传时从最新
        消息开始读取；返回的 ``next_before`` 可用于继续向更早历史翻页。
        """
        user_id_str = str(user_id)
        history = self._private_message_history.get(user_id_str, [])
        total = len(history)
        if total == 0 or limit <= 0:
            return [], False, None, total

        end = total if before is None else max(0, min(before, total))
        start = max(0, end - limit)
        items = history[start:end]
        has_more = start > 0
        next_before = start if has_more else None
        return items, has_more, next_before, total

    async def clear_private_history(self, user_id: int) -> int:
        """清空指定私聊会话的内存与落盘历史，返回清空前记录数。"""
        await self._ensure_initialized()

        user_id_str = str(user_id)
        path = self._get_private_history_path(user_id)
        async with self._get_private_lock(user_id_str):
            previous_count = len(self._private_message_history.get(user_id_str, []))
            self._private_message_history[user_id_str] = []
            self._queue_history_save([], path)

        # 等待空数组写入，避免正在运行的旧保存任务最终把旧历史恢复到文件。
        await self.flush_pending_saves()
        return previous_count

    async def modify_last_group_message(
        self,
        group_id: int,
        sender_id: int,
        new_message: str,
    ) -> None:
        """异步修改群聊历史记录中指定用户的最后一条消息"""
        await self._ensure_initialized()

        group_id_str = str(group_id)
        sender_id_str = str(sender_id)

        if group_id_str not in self._message_history:
            return

        async with self._get_group_lock(group_id_str):
            # 查找并修改消息
            for i in range(len(self._message_history[group_id_str]) - 1, -1, -1):
                msg = self._message_history[group_id_str][i]
                if msg.get("user_id") == sender_id_str:
                    old_length = len(msg["message"])
                    new_length = len(new_message)
                    msg["message"] = new_message

                    logger.debug(
                        f"[历史记录] 修改群消息: group={group_id}, user={sender_id}, "
                        f"old_len={old_length}, new_len={new_length}"
                    )

                    # 后台合并保存，避免安全检测路径阻塞在全量落盘上。
                    self._queue_history_save(
                        self._message_history[group_id_str],
                        self._get_group_history_path(group_id),
                    )
                    logger.info(
                        f"已修改群聊 {group_id} 用户 {sender_id} 的最后一条消息"
                    )
                    break

    async def modify_last_private_message(
        self,
        user_id: int,
        new_message: str,
    ) -> None:
        """异步修改私聊历史记录中最后一条消息"""
        await self._ensure_initialized()

        user_id_str = str(user_id)

        if user_id_str not in self._private_message_history:
            return

        async with self._get_private_lock(user_id_str):
            if self._private_message_history[user_id_str]:
                old_length = len(
                    self._private_message_history[user_id_str][-1]["message"]
                )
                new_length = len(new_message)

                self._private_message_history[user_id_str][-1]["message"] = new_message

                logger.debug(
                    f"[历史记录] 修改私聊消息: user={user_id}, "
                    f"old_len={old_length}, new_len={new_length}"
                )

                # 后台合并保存，避免安全检测路径阻塞在全量落盘上。
                self._queue_history_save(
                    self._private_message_history[user_id_str],
                    self._get_private_history_path(user_id),
                )
                logger.info(f"已修改私聊用户 {user_id} 的最后一条消息")
