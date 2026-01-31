"""速率限制模块"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Undefined.config import Config


class RateLimiter:
    """速率限制器

    规则：
    - 超级管理员：无限制
    - 管理员：5秒/次
    - 普通用户：10秒/次
    - /ask 命令：1分钟/次（所有人）
    """

    # 冷却时间（秒）
    ADMIN_COOLDOWN = 5
    USER_COOLDOWN = 10
    ASK_COOLDOWN = 60  # /ask 命令：1分钟

    def __init__(self, config: "Config") -> None:
        self.config = config
        # 记录每个用户最后一次调用时间
        # 格式: {user_id: last_call_time}
        self._last_calls: dict[int, float] = {}
        # /ask 命令单独记录
        self._last_ask_calls: dict[int, float] = {}

    def check(self, user_id: int) -> tuple[bool, int]:
        """检查用户是否可以执行命令

        参数:
            user_id: 用户 QQ 号

        返回:
            (是否允许, 剩余等待秒数)
        """
        # 超级管理员无限制
        if self.config.is_superadmin(user_id):
            return (True, 0)

        now = time.time()
        last_call = self._last_calls.get(user_id, 0)

        # 确定冷却时间
        if self.config.is_admin(user_id):
            cooldown = self.ADMIN_COOLDOWN
        else:
            cooldown = self.USER_COOLDOWN

        elapsed = now - last_call

        if elapsed >= cooldown:
            return (True, 0)
        else:
            remaining = int(cooldown - elapsed) + 1
            return (False, remaining)

    def check_ask(self, user_id: int) -> tuple[bool, int]:
        """检查用户是否可以使用 /ask 命令

        参数:
            user_id: 用户 QQ 号

        返回:
            (是否允许, 剩余等待秒数)
        """
        # 超级管理员无限制
        if self.config.is_superadmin(user_id):
            return (True, 0)

        now = time.time()
        last_call = self._last_ask_calls.get(user_id, 0)

        elapsed = now - last_call

        if elapsed >= self.ASK_COOLDOWN:
            return (True, 0)
        else:
            remaining = int(self.ASK_COOLDOWN - elapsed) + 1
            return (False, remaining)

    def record(self, user_id: int) -> None:
        """记录用户调用时间

        参数:
            user_id: 用户 QQ 号
        """
        # 超级管理员不记录
        if self.config.is_superadmin(user_id):
            return

        self._last_calls[user_id] = time.time()

    def record_ask(self, user_id: int) -> None:
        """记录用户 /ask 命令调用时间

        参数:
            user_id: 用户 QQ 号
        """
        # 超级管理员不记录
        if self.config.is_superadmin(user_id):
            return

        self._last_ask_calls[user_id] = time.time()

    def clear(self, user_id: int) -> None:
        """清除用户的限制记录

        参数:
            user_id: 用户 QQ 号
        """
        self._last_calls.pop(user_id, None)

    def clear_ask(self, user_id: int) -> None:
        """清除用户的 /ask 命令限制记录

        参数:
            user_id: 用户 QQ 号
        """
        self._last_ask_calls.pop(user_id, None)

    def clear_all(self) -> None:
        """清除所有限制记录"""
        self._last_calls.clear()
        self._last_ask_calls.clear()
