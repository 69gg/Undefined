"""速率限制模块"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Undefined.config import Config
    from Undefined.services.commands.registry import CommandRateLimit


class RateLimiter:
    """速率限制器

    规则：
    - 超级管理员：无限制
    - 管理员：5秒/次
    - 普通用户：10秒/次
    - /ask 命令：1分钟/次（所有人）
    - /stats 命令：1小时/次（普通用户），管理员无限制
    """

    # 冷却时间（秒）
    ADMIN_COOLDOWN = 5
    USER_COOLDOWN = 10
    ASK_COOLDOWN = 60  # /ask 命令：1分钟
    STATS_COOLDOWN = 3600  # /stats 命令：1小时（普通用户）

    def __init__(self, config: "Config") -> None:
        self.config = config
        # 记录每个用户最后一次调用时间
        # 格式: {user_id: last_call_time}
        self._last_calls: dict[int, float] = {}
        # /ask 命令单独记录
        self._last_ask_calls: dict[int, float] = {}
        # /stats 命令单独记录
        self._last_stats_calls: dict[int, float] = {}
        # 动态命令单独记录
        # 格式: {command_name: {user_id: last_call_time}}
        self._command_calls: dict[str, dict[int, float]] = {}

    def check_command(
        self, user_id: int, command_name: str, limits: "CommandRateLimit"
    ) -> tuple[bool, int]:
        """检查用户是否可以执行特定命令

        参数:
            user_id: 用户 QQ 号
            command_name: 命令的唯一名称
            limits: 命令的速率限制规则

        返回:
            (是否允许, 剩余等待秒数)
        """
        if self.config.is_superadmin(user_id):
            cooldown = limits.superadmin
        elif self.config.is_admin(user_id):
            cooldown = limits.admin
        else:
            cooldown = limits.user

        if cooldown <= 0:
            return (True, 0)

        now = time.time()
        cmd_records = self._command_calls.setdefault(command_name, {})
        last_call = cmd_records.get(user_id, 0.0)

        elapsed = now - last_call
        if elapsed >= cooldown:
            return (True, 0)
        else:
            remaining = int(cooldown - elapsed) + 1
            return (False, remaining)

    def record_command(
        self, user_id: int, command_name: str, limits: "CommandRateLimit"
    ) -> None:
        """记录特定命令的调用时间

        参数:
            user_id: 用户 QQ 号
            command_name: 命令的唯一名称
            limits: 命令的速率限制规则
        """
        if self.config.is_superadmin(user_id):
            cooldown = limits.superadmin
        elif self.config.is_admin(user_id):
            cooldown = limits.admin
        else:
            cooldown = limits.user

        if cooldown <= 0:
            return

        cmd_records = self._command_calls.setdefault(command_name, {})
        cmd_records[user_id] = time.time()

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

    def check_stats(self, user_id: int) -> tuple[bool, int]:
        """检查用户是否可以使用 /stats 命令

        规则：
        - 超级管理员和管理员：无限制
        - 普通用户：1小时/次

        参数:
            user_id: 用户 QQ 号

        返回:
            (是否允许, 剩余等待秒数)
        """
        # 超级管理员和管理员无限制
        if self.config.is_superadmin(user_id) or self.config.is_admin(user_id):
            return (True, 0)

        now = time.time()
        last_call = self._last_stats_calls.get(user_id, 0)

        elapsed = now - last_call

        if elapsed >= self.STATS_COOLDOWN:
            return (True, 0)
        else:
            remaining = int(self.STATS_COOLDOWN - elapsed) + 1
            return (False, remaining)

    def record_stats(self, user_id: int) -> None:
        """记录用户 /stats 命令调用时间

        参数:
            user_id: 用户 QQ 号
        """
        # 超级管理员和管理员不记录
        if self.config.is_superadmin(user_id) or self.config.is_admin(user_id):
            return

        self._last_stats_calls[user_id] = time.time()

    def clear_stats(self, user_id: int) -> None:
        """清除用户的 /stats 命令限制记录

        参数:
            user_id: 用户 QQ 号
        """
        self._last_stats_calls.pop(user_id, None)

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
        self._last_stats_calls.clear()
        self._command_calls.clear()
