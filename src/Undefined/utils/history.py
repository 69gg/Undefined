"""历史记录管理"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 历史记录文件路径
HISTORY_DIR = os.path.join("data", "history")


def _extract_id_from_history_filename(path: str, prefix: str) -> str:
    filename = os.path.basename(path)
    if filename.startswith(prefix) and filename.endswith(".json"):
        return filename[len(prefix) : -5]
    return ""


class MessageHistoryManager:
    """消息历史管理器（异步，Lazy Load）"""

    def __init__(self, max_records: int = 10000) -> None:
        self._max_records = max_records
        self._message_history: dict[str, list[dict[str, Any]]] = {}
        self._private_message_history: dict[str, list[dict[str, Any]]] = {}
        self._group_locks: dict[str, asyncio.Lock] = {}
        self._private_locks: dict[str, asyncio.Lock] = {}

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
        """异步保存历史记录到文件（最多 10000 条）"""
        from Undefined.utils import io

        try:
            # 只保留最近的 self._max_records 条
            truncated_history = (
                history[-self._max_records :]
                if len(history) > self._max_records
                else history
            )
            truncated = len(history) > self._max_records

            logger.debug(
                f"[历史记录] 准备保存: path={path}, total={len(history)}, truncated={truncated}"
            )

            await io.write_json(path, truncated_history, use_lock=True)

            logger.debug(f"[历史记录] 保存成功: path={path}")
        except Exception as e:
            logger.error(f"[历史记录错误] 保存历史记录失败 {path}: {e}")

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

                    normalized_history.append(msg)

                # 只保留最近的 self._max_records 条
                return (
                    normalized_history[-self._max_records :]
                    if len(normalized_history) > self._max_records
                    else normalized_history
                )
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

            self._message_history[group_id_str].append(
                {
                    "type": "group",
                    "chat_id": group_id_str,
                    "chat_name": group_name or f"群{group_id_str}",
                    "user_id": sender_id_str,
                    "display_name": display_name,
                    "role": role,
                    "title": title,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "message": text_content,
                }
            )

            if len(self._message_history[group_id_str]) > self._max_records:
                self._message_history[group_id_str] = self._message_history[
                    group_id_str
                ][-self._max_records :]

            await self._save_history_to_file(
                self._message_history[group_id_str],
                self._get_group_history_path(group_id),
            )

    async def add_private_message(
        self,
        user_id: int,
        text_content: str,
        display_name: str = "",
        user_name: str = "",
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

            self._private_message_history[user_id_str].append(
                {
                    "type": "private",
                    "chat_id": user_id_str,
                    "chat_name": user_name or f"QQ用户{user_id_str}",
                    "user_id": user_id_str,
                    "display_name": display_name or user_name or user_id_str,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "message": text_content,
                }
            )

            if len(self._private_message_history[user_id_str]) > self._max_records:
                self._private_message_history[user_id_str] = (
                    self._private_message_history[user_id_str][-self._max_records :]
                )

            await self._save_history_to_file(
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

                    # 原子保存
                    await self._save_history_to_file(
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

                # 原子保存
                await self._save_history_to_file(
                    self._private_message_history[user_id_str],
                    self._get_private_history_path(user_id),
                )
                logger.info(f"已修改私聊用户 {user_id} 的最后一条消息")
