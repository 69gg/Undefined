"""统一的请求上下文管理系统

基于 Python contextvars 实现请求级别的上下文隔离和自动传播。
"""

from contextvars import ContextVar
from typing import Any, Optional
import uuid
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 全局 ContextVar - 每个异步任务有独立的副本
_request_context: ContextVar[Optional["RequestContext"]] = ContextVar(
    "request_context", default=None
)


class RequestContext:
    """统一的请求上下文管理器

    使用方式:
        async with RequestContext(request_type="group", group_id=123, sender_id=456):
            # 在此作用域内，所有代码都可以通过 RequestContext.current() 获取上下文
            await process_request()

    特性:
        - 自动分配唯一的 request_id (UUID)
        - 完全的并发隔离（基于 contextvars）
        - 自动资源管理和清理
        - 支持嵌套上下文
    """

    def __init__(
        self,
        request_type: str,  # "group" | "private"
        group_id: Optional[int] = None,
        user_id: Optional[int] = None,
        sender_id: Optional[int] = None,
        **metadata: Any,
    ):
        # 核心ID
        self.request_id = str(uuid.uuid4())
        self.timestamp = datetime.now()

        # 业务ID
        self.request_type = request_type
        self.group_id = group_id
        self.user_id = user_id
        self.sender_id = sender_id

        # 元数据
        self.metadata = metadata

        # 资源容器 - 存储请求级别的资源（如 sender, history_manager 等）
        self._resources: dict[str, Any] = {}

        # Token用于恢复上下文
        self._token: Any = None

    def set_resource(self, name: str, value: Any) -> None:
        """设置请求级别的资源

        Args:
            name: 资源名称
            value: 资源对象
        """
        self._resources[name] = value

    def get_resource(self, name: str, default: Any = None) -> Any:
        """获取请求级别的资源

        Args:
            name: 资源名称
            default: 默认值

        Returns:
            资源对象，如果不存在则返回 default
        """
        return self._resources.get(name, default)

    @classmethod
    def current(cls) -> Optional["RequestContext"]:
        """获取当前请求上下文

        Returns:
            当前的 RequestContext 实例，如果不在请求上下文中则返回 None
        """
        return _request_context.get()

    @classmethod
    def require(cls) -> "RequestContext":
        """获取当前请求上下文（必须存在）

        Returns:
            当前的 RequestContext 实例

        Raises:
            RuntimeError: 如果当前不在请求上下文中
        """
        ctx = cls.current()
        if ctx is None:
            raise RuntimeError(
                "No active request context. "
                "Make sure you're calling this within an 'async with RequestContext(...)' block."
            )
        return ctx

    async def __aenter__(self) -> "RequestContext":
        """进入上下文管理器"""
        self._token = _request_context.set(self)
        logger.debug(
            f"[RequestContext] 创建请求上下文: "
            f"request_id={self.request_id}, "
            f"type={self.request_type}, "
            f"group_id={self.group_id}, "
            f"user_id={self.user_id}"
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """退出上下文管理器，自动清理"""
        logger.debug(f"[RequestContext] 清理请求上下文: request_id={self.request_id}")
        _request_context.reset(self._token)
        # 清理资源
        self._resources.clear()


# ============================================================================
# 便捷访问函数 - 简化常用属性的访问
# ============================================================================


def get_group_id() -> Optional[int]:
    """获取当前请求的群ID

    Returns:
        群ID，如果不在群聊上下文中则返回 None
    """
    ctx = RequestContext.current()
    return ctx.group_id if ctx else None


def get_user_id() -> Optional[int]:
    """获取当前请求的用户ID

    Returns:
        用户ID，如果不在私聊上下文中则返回 None
    """
    ctx = RequestContext.current()
    return ctx.user_id if ctx else None


def get_request_id() -> Optional[str]:
    """获取当前请求ID (UUID)

    Returns:
        请求ID，如果不在请求上下文中则返回 None
    """
    ctx = RequestContext.current()
    return ctx.request_id if ctx else None


def get_sender_id() -> Optional[int]:
    """获取当前请求的发送者ID

    Returns:
        发送者ID，如果不在请求上下文中则返回 None
    """
    ctx = RequestContext.current()
    return ctx.sender_id if ctx else None


def get_request_type() -> Optional[str]:
    """获取当前请求类型

    Returns:
        请求类型 ("group" | "private")，如果不在请求上下文中则返回 None
    """
    ctx = RequestContext.current()
    return ctx.request_type if ctx else None


# ============================================================================
# 日志集成 - 自动为日志添加请求上下文信息
# ============================================================================


class RequestContextFilter(logging.Filter):
    """日志过滤器，自动为日志记录添加请求上下文信息

    使用方式:
        import logging
        from Undefined.context import RequestContextFilter

        # 为所有 handler 添加过滤器
        for handler in logging.root.handlers:
            handler.addFilter(RequestContextFilter())

    日志格式建议:
        '%(asctime)s [%(levelname)s] [%(request_id)s] [g:%(group_id)s|u:%(user_id)s] %(name)s: %(message)s'
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """为日志记录添加请求上下文字段"""
        ctx = RequestContext.current()
        if ctx:
            record.request_id = ctx.request_id[:8]  # 使用短ID
            record.group_id = ctx.group_id or "-"
            record.user_id = ctx.user_id or "-"
            record.sender_id = ctx.sender_id or "-"
        else:
            record.request_id = "-"
            record.group_id = "-"
            record.user_id = "-"
            record.sender_id = "-"
        return True
