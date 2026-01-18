"""历史记录管理"""

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 历史记录文件路径
HISTORY_DIR = os.path.join("data", "history")
MAX_HISTORY = 10000  # 统一 10000 条限制


class MessageHistoryManager:
    """消息历史管理器"""

    def __init__(self) -> None:
        self._message_history: dict[str, list[dict[str, Any]]] = {}
        self._private_message_history: dict[str, list[dict[str, Any]]] = {}
        # 确保目录存在
        os.makedirs(HISTORY_DIR, exist_ok=True)
        # 加载历史
        self._load_all_histories()

    def _get_group_history_path(self, group_id: int) -> str:
        """获取群消息历史文件路径"""
        return os.path.join(HISTORY_DIR, f"group_{group_id}.json")

    def _get_private_history_path(self, user_id: int) -> str:
        """获取私聊消息历史文件路径"""
        return os.path.join(HISTORY_DIR, f"private_{user_id}.json")

    def _save_history_to_file(self, history: list[dict[str, Any]], path: str) -> None:
        """保存历史记录到文件（最多 10000 条）"""
        try:
            # 只保留最近的 MAX_HISTORY 条
            truncated_history = (
                history[-MAX_HISTORY:] if len(history) > MAX_HISTORY else history
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(truncated_history, f, ensure_ascii=False, indent=2)
            logger.debug(f"[历史记录] 已成功保存历史到 {path}")
        except Exception as e:
            logger.error(f"[历史记录错误] 保存历史记录失败 {path}: {e}")

    def _load_history_from_file(self, path: str) -> list[dict[str, Any]]:
        """从文件加载历史记录"""
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if isinstance(history, list):
                        # 兼容旧格式：补充缺失的字段
                        for msg in history:
                            if "type" not in msg:
                                msg["type"] = (
                                    "private" if "private" in path else "group"
                                )
                            if "chat_id" not in msg:
                                if "group_" in path:
                                    msg["chat_id"] = msg.get("user_id", "")
                                else:
                                    msg["chat_id"] = msg.get("user_id", "")
                            if "timestamp" not in msg:
                                msg["timestamp"] = ""
                            if "chat_name" not in msg:
                                if msg["type"] == "group":
                                    msg["chat_name"] = f"群{msg.get('chat_id', '')}"
                                else:
                                    msg["chat_name"] = f"QQ用户{msg.get('chat_id', '')}"
                        # 只保留最近的 MAX_HISTORY 条
                        return (
                            history[-MAX_HISTORY:]
                            if len(history) > MAX_HISTORY
                            else history
                        )
        except Exception as e:
            logger.error(f"加载历史记录失败 {path}: {e}")
        return []

    def _load_all_histories(self) -> None:
        """启动时加载所有历史记录"""
        if not os.path.exists(HISTORY_DIR):
            logger.info("历史消息目录不存在，跳过加载")
            return

        # 加载群消息历史
        group_count = 0
        for filename in os.listdir(HISTORY_DIR):
            if filename.startswith("group_") and filename.endswith(".json"):
                try:
                    group_id_str = filename[6:-5]  # 提取群号
                    path = os.path.join(HISTORY_DIR, filename)
                    self._message_history[group_id_str] = self._load_history_from_file(
                        path
                    )
                    group_count += 1
                    logger.debug(
                        f"[历史记录] 已加载群 {group_id_str} 历史消息: {len(self._message_history[group_id_str])} 条"
                    )
                except Exception as e:
                    logger.error(f"[历史记录错误] 加载群历史失败 {filename}: {e}")

        logger.info(f"[历史记录] 共加载了 {group_count} 个群聊的历史记录")

        # 加载私聊消息历史
        private_count = 0
        for filename in os.listdir(HISTORY_DIR):
            if filename.startswith("private_") and filename.endswith(".json"):
                try:
                    user_id_str = filename[8:-5]  # 提取用户ID
                    path = os.path.join(HISTORY_DIR, filename)
                    self._private_message_history[user_id_str] = (
                        self._load_history_from_file(path)
                    )
                    private_count += 1
                    logger.debug(
                        f"[历史记录] 已加载私聊 {user_id_str} 历史消息: {len(self._private_message_history[user_id_str])} 条"
                    )
                except Exception as e:
                    logger.error(f"[历史记录错误] 加载私聊历史失败 {filename}: {e}")

        logger.info(f"[历史记录] 共加载了 {private_count} 个私聊会话的历史记录")

    def add_group_message(
        self,
        group_id: int,
        sender_id: int,
        text_content: str,
        sender_card: str = "",
        sender_nickname: str = "",
        group_name: str = "",
    ) -> None:
        """保存群消息到历史记录"""
        group_id_str = str(group_id)
        sender_id_str = str(sender_id)

        if group_id_str not in self._message_history:
            self._message_history[group_id_str] = []

        display_name = sender_card or sender_nickname or sender_id_str

        self._message_history[group_id_str].append(
            {
                "type": "group",
                "chat_id": group_id_str,
                "chat_name": group_name or f"群{group_id_str}",
                "user_id": sender_id_str,
                "display_name": display_name,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": text_content,
            }
        )

        if len(self._message_history[group_id_str]) > MAX_HISTORY:
            self._message_history[group_id_str] = self._message_history[group_id_str][
                -MAX_HISTORY:
            ]

        self._save_history_to_file(
            self._message_history[group_id_str], self._get_group_history_path(group_id)
        )

    def add_private_message(
        self,
        user_id: int,
        text_content: str,
        display_name: str = "",
        user_name: str = "",
    ) -> None:
        """保存私聊消息到历史记录"""
        user_id_str = str(user_id)

        if user_id_str not in self._private_message_history:
            self._private_message_history[user_id_str] = []

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

        if len(self._private_message_history[user_id_str]) > MAX_HISTORY:
            self._private_message_history[user_id_str] = self._private_message_history[
                user_id_str
            ][-MAX_HISTORY:]

        self._save_history_to_file(
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

    def modify_last_group_message(
        self,
        group_id: int,
        sender_id: int,
        new_message: str,
    ) -> None:
        """修改群聊历史记录中指定用户的最后一条消息"""
        group_id_str = str(group_id)
        sender_id_str = str(sender_id)

        if group_id_str not in self._message_history:
            return

        for i in range(len(self._message_history[group_id_str]) - 1, -1, -1):
            msg = self._message_history[group_id_str][i]
            if msg.get("user_id") == sender_id_str:
                msg["message"] = new_message
                self._save_history_to_file(
                    self._message_history[group_id_str],
                    self._get_group_history_path(group_id),
                )
                logger.info(f"已修改群聊 {group_id} 用户 {sender_id} 的最后一条消息")
                break

    def modify_last_private_message(
        self,
        user_id: int,
        new_message: str,
    ) -> None:
        """修改私聊历史记录中最后一条消息"""
        user_id_str = str(user_id)

        if user_id_str not in self._private_message_history:
            return

        if self._private_message_history[user_id_str]:
            self._private_message_history[user_id_str][-1]["message"] = new_message
            self._save_history_to_file(
                self._private_message_history[user_id_str],
                self._get_private_history_path(user_id),
            )
            logger.info(f"已修改私聊用户 {user_id} 的最后一条消息")
