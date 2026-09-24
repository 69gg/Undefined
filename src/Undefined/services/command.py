import asyncio
import logging
import re
import time
from uuid import uuid4
from typing import Any, Awaitable, Callable, Optional, cast
from pathlib import Path

from Undefined.config import Config
from Undefined.faq import FAQStorage
from Undefined.onebot import OneBotClient
from Undefined.utils.sender import MessageSender
from Undefined.services.bugfix_command import BugfixCommandMixin
from Undefined.services.commands.context import (
    CommandContext,
    CommandSender,
    PrivateForwardCallback,
    PrivateMessageCallback,
)
from Undefined.services.commands.registry import (
    CommandRateLimit,
    CommandRegistry,
)
from Undefined.services.security import SecurityService
from Undefined.services.stats_command import StatsCommandMixin
from Undefined.token_usage_storage import TokenUsageStorage

logger = logging.getLogger(__name__)


# 命令参数中的 @ 提及：[@QQ] / [@QQ(昵称)] / [@{QQ}]
_AT_ARG_RE = re.compile(r"^\[@\s*\{?(\d{5,15})\}?(?:\(.*?\))?\]$")
_ARG_TOKEN_RE = re.compile(r"\[@\s*\{?\d{5,15}\}?(?:\([^\]]*\))?\]|\S+")


def _normalize_qq_arg(arg: str) -> str:
    """将命令参数里的 @ 提及归一化为纯数字 QQ 号。

    命中 ``[@QQ号]`` / ``[@QQ号(昵称)]`` / ``[@{QQ号}]`` 时返回 ``"QQ号"``，
    否则原样返回。命令实现因此可以始终把参数当作纯数字处理。
    """
    if not arg:
        return arg
    match = _AT_ARG_RE.match(arg.strip())
    return match.group(1) if match else arg


def _split_command_args(args_str: str) -> list[str]:
    """按空白拆分命令参数，同时保留完整的 ``[@QQ(昵称)]`` 片段。"""
    if not args_str.strip():
        return []
    return [match.group(0) for match in _ARG_TOKEN_RE.finditer(args_str)]


class _PrivateCommandSenderProxy:
    """将命令处理器里的 send_group_message 代理到私聊发送。"""

    def __init__(
        self,
        user_id: int,
        send_private_message: PrivateMessageCallback,
        send_private_forward_message: PrivateForwardCallback | None = None,
    ) -> None:
        self._user_id = user_id
        self._send_private_message = send_private_message
        self._send_private_forward_message = send_private_forward_message

    @property
    def supports_private_forward(self) -> bool:
        return self._send_private_forward_message is not None

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | None:
        _ = (
            group_id,
            auto_history,
            history_prefix,
            mark_sent,
            reply_to,
            history_message,
            attachments,
        )
        await self._send_private_message(self._user_id, message)
        return None

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> int | str | None:
        _ = (
            user_id,
            auto_history,
            mark_sent,
            reply_to,
            preferred_temp_group_id,
            history_message,
            attachments,
        )
        await self._send_private_message(self._user_id, message)
        return None

    async def send_private_forward_message(
        self,
        user_id: int,
        messages: list[dict[str, Any]],
        *,
        history_message: str,
        auto_history: bool = True,
    ) -> None:
        _ = user_id
        if self._send_private_forward_message is None:
            raise RuntimeError("当前私聊命令通道不支持合并转发")
        await self._send_private_forward_message(
            self._user_id,
            messages,
            history_message=history_message,
            auto_history=auto_history,
        )


class CommandDispatcher(BugfixCommandMixin, StatsCommandMixin):
    """命令分发处理器，负责解析和执行斜杠命令"""

    def __init__(
        self,
        config: Config,
        sender: MessageSender,
        ai: Any,  # AIClient
        faq_storage: FAQStorage,
        onebot: OneBotClient,
        security: SecurityService,
        queue_manager: Any = None,
        rate_limiter: Any = None,
        history_manager: Any = None,
    ) -> None:
        """初始化命令分发器

        参数:
            config: 全局配置实例
            sender: 消息发送助手
            ai: AI 客户端(用于归纳和标题生成)
            faq_storage: FAQ 存储管理器
            onebot: OneBot HTTP API 客户端
            security: 安全审计与限流服务
            queue_manager: AI 请求队列管理器
            rate_limiter: 速率限制器
            history_manager: 消息历史记录管理器
        """
        self.config = config
        self.sender = sender
        self.ai = ai
        self.faq_storage = faq_storage
        self.onebot = onebot
        self.security = security
        self.queue_manager = queue_manager
        self.rate_limiter = rate_limiter
        self.history_manager = history_manager
        self.naga_store: Any = None
        self._token_usage_storage = TokenUsageStorage()
        # 存储 stats 分析结果，用于队列回调
        self._stats_analysis_results: dict[str, str] = {}
        self._stats_analysis_events: dict[str, asyncio.Event] = {}
        self._stats_render_lock = asyncio.Lock()

        # 加载所有命令实现 (独立插件形式存放在 skills/commands 目录下)
        commands_dir = Path(__file__).parent.parent / "skills" / "commands"
        self.command_registry = CommandRegistry(commands_dir)
        self.command_registry.load_commands()
        logger.info("[命令] 命令系统初始化完成: dir=%s", commands_dir)

    def parse_command(self, text: str) -> Optional[dict[str, Any]]:
        """解析斜杠命令字符串

        参数:
            text: 原始文本内容

        返回:
            包含命令名(name)和参数列表(args)的字典，解析失败则返回 None

        说明:
            - 仅剥离开头的 @ 机器人提及，保留命令参数中的真 @
            - 自动将参数里的 ``[@QQ号]`` / ``[@QQ号(昵称)]`` / ``[@{QQ号}]``
              归一化为纯数字 QQ 号，命令实现无需关心格式差异
        """
        clean_text = re.sub(r"^(?:\[@\s*\d+(?:\(.*?\))?\]\s*)+", "", text).strip()
        match = re.match(r"/(\w+)\s*(.*)", clean_text)
        if not match:
            return None

        cmd_name = match.group(1).lower()
        args_str = match.group(2).strip()
        raw_args = _split_command_args(args_str)
        args = [_normalize_qq_arg(arg) for arg in raw_args]

        logger.debug(
            "[命令] 解析命令: text_len=%s cmd=%s args=%s",
            len(text),
            cmd_name,
            args_str,
        )
        return {
            "name": cmd_name,
            "args": args,
        }

    async def dispatch(
        self, group_id: int, sender_id: int, command: dict[str, Any]
    ) -> None:
        await self._dispatch_internal(
            scope="group",
            group_id=group_id,
            sender_id=sender_id,
            command=command,
            user_id=None,
            send_private_callback=None,
            command_sender=None,
        )

    async def dispatch_private(
        self,
        user_id: int,
        sender_id: int,
        command: dict[str, Any],
        send_private_callback: PrivateMessageCallback | None = None,
        is_webui_session: bool = False,
        command_sender: object | None = None,
    ) -> None:
        await self._dispatch_internal(
            scope="private",
            group_id=0,
            sender_id=sender_id,
            command=command,
            user_id=user_id,
            send_private_callback=send_private_callback,
            is_webui_session=is_webui_session,
            command_sender=command_sender,
        )

    async def _dispatch_internal(
        self,
        *,
        scope: str,
        group_id: int,
        sender_id: int,
        command: dict[str, Any],
        user_id: int | None,
        send_private_callback: PrivateMessageCallback | None,
        is_webui_session: bool = False,
        command_sender: object | None = None,
    ) -> None:
        """统一分发入口：支持群聊与私聊。"""
        start_time = time.perf_counter()
        cmd_name = str(command["name"])
        cmd_args = command["args"]

        private_delivery: PrivateMessageCallback | None = None
        private_forward: PrivateForwardCallback | None = None
        if scope == "private":
            if command_sender is not None:
                route_sender = command_sender
                route_private = getattr(route_sender, "send_private_message", None)
                if not callable(route_private):
                    raise TypeError("私聊命令发送器缺少 send_private_message")
                private_delivery = cast(PrivateMessageCallback, route_private)
                route_forward = getattr(
                    route_sender, "send_private_forward_message", None
                )
                if callable(route_forward):
                    private_forward = cast(PrivateForwardCallback, route_forward)
            elif send_private_callback is not None:
                private_delivery = send_private_callback
            else:
                private_delivery = self.sender.send_private_message
                default_forward = getattr(
                    self.sender, "send_private_forward_message", None
                )
                if callable(default_forward):
                    private_forward = cast(PrivateForwardCallback, default_forward)

        if scope == "private":
            logger.debug(
                "[命令] 分发请求: private user=%s sender=%s cmd=%s args_count=%s",
                user_id,
                sender_id,
                cmd_name,
                len(cmd_args),
            )
            target_log = f"private={user_id}"
        else:
            logger.debug(
                "[命令] 分发请求: group=%s sender=%s cmd=%s args_count=%s",
                group_id,
                sender_id,
                cmd_name,
                len(cmd_args),
            )
            target_log = f"group={group_id}"

        async def _send_target_message(message: str) -> None:
            if scope == "private":
                if user_id is None:
                    logger.warning("[命令] 私聊命令无法发送：user_id 为 None")
                    return
                if private_delivery is None:
                    raise RuntimeError("私聊命令发送器尚未解析")
                await private_delivery(int(user_id), message)
            else:
                await self.sender.send_group_message(group_id, message)

        logger.info(
            "[命令] 执行命令: /%s | 参数=%s | %s", cmd_name, cmd_args, target_log
        )

        self.command_registry.maybe_reload()
        meta = self.command_registry.resolve(cmd_name)
        if meta is None:
            logger.info("[命令] 未知命令: /%s", cmd_name)
            await _send_target_message(
                f"❌ 未知命令: {cmd_name}\n使用 /help 查看可用命令"
            )
            return

        logger.info(
            "[命令] 命令匹配成功: input=/%s resolved=/%s permission=%s rate_limit=%s private=%s",
            cmd_name,
            meta.name,
            meta.permission,
            meta.rate_limit,
            meta.allow_in_private,
        )

        if cmd_args and cmd_args[0] == "--help":
            await _send_target_message(
                f"⚠️ 参数 --help 已弃用\n请使用：/help {meta.name}"
            )
            return

        # ── 子命令解析与推断 ──
        subcmd_name: str | None = None
        subcmd_meta = None
        if meta.subcommands:
            subcmd_name, cmd_args, subcmd_meta = (
                self.command_registry.resolve_subcommand(meta, cmd_args)
            )

        # 确定实际用于权限/作用域/限流检查的元信息
        effective_permission = (
            subcmd_meta.permission if subcmd_meta else meta.permission
        )
        effective_allow_private = (
            subcmd_meta.allow_in_private if subcmd_meta else meta.allow_in_private
        )
        effective_rate_limit = (
            subcmd_meta.rate_limit if subcmd_meta else meta.rate_limit
        )
        rate_limit_key = (
            meta.name if subcmd_name is None else f"{meta.name}:{subcmd_name}"
        )

        # 作用域检查（子命令可能覆盖 allow_in_private）
        if scope == "private" and not effective_allow_private:
            logger.info(
                "[命令] 私聊作用域禁用: /%s subcmd=%s user=%s",
                meta.name,
                subcmd_name,
                user_id,
            )
            await _send_target_message(
                f"⚠️ /{meta.name} 当前不支持私聊使用。请在群聊中 @机器人 后执行。"
            )
            return

        allowed, role_name = self._check_command_permission_raw(
            effective_permission, sender_id
        )
        if not allowed:
            logger.warning(
                "[命令] 权限校验失败: cmd=/%s subcmd=%s sender=%s required=%s",
                meta.name,
                subcmd_name,
                sender_id,
                role_name,
            )
            await self._send_no_permission(
                sender_id=sender_id,
                cmd_name=meta.name,
                required_role=role_name,
                send_message=_send_target_message,
            )
            return

        logger.debug("[命令] 权限校验通过: cmd=/%s sender=%s", meta.name, sender_id)

        if not await self._check_command_rate_limit(
            rate_limit=effective_rate_limit,
            command_name=meta.name,
            rate_limit_key=rate_limit_key,
            sender_id=sender_id,
            send_message=_send_target_message,
        ):
            logger.warning(
                "[命令] 速率限制拦截: cmd=/%s subcmd=%s scope=%s sender=%s",
                meta.name,
                subcmd_name,
                scope,
                sender_id,
            )
            return

        logger.debug("[命令] 速率限制通过: cmd=/%s sender=%s", meta.name, sender_id)

        if scope == "private":
            if private_delivery is None:
                raise RuntimeError("私聊命令发送器尚未解析")
            context_sender: CommandSender = _PrivateCommandSenderProxy(
                int(user_id or 0),
                private_delivery,
                private_forward,
            )
        else:
            context_sender = self.sender

        context = CommandContext(
            group_id=group_id,
            sender_id=sender_id,
            config=self.config,
            sender=context_sender,
            ai=self.ai,
            faq_storage=self.faq_storage,
            onebot=self.onebot,
            security=self.security,
            queue_manager=self.queue_manager,
            rate_limiter=self.rate_limiter,
            dispatcher=self,
            registry=self.command_registry,
            scope=scope,
            user_id=user_id,
            is_webui_session=is_webui_session,
            cognitive_service=getattr(self.ai, "_cognitive_service", None),
            history_manager=self.history_manager,
            resolved_subcommand=subcmd_name,
        )

        try:
            await self.command_registry.execute(meta, cmd_args, context)
            duration = time.perf_counter() - start_time
            logger.info("[命令] 分发完成: cmd=/%s duration=%.3fs", meta.name, duration)
        except Exception as e:
            duration = time.perf_counter() - start_time
            error_id = uuid4().hex[:8]
            logger.exception(
                "[命令] 执行失败: cmd=/%s error_id=%s err=%s",
                meta.name,
                error_id,
                e,
            )
            logger.error(
                "[命令] 分发失败: cmd=/%s duration=%.3fs error_id=%s",
                meta.name,
                duration,
                error_id,
            )
            await _send_target_message(
                f"❌ 命令执行失败，请稍后重试（错误码: {error_id}）"
            )

    def _check_command_permission_raw(
        self,
        permission: str,
        sender_id: int,
    ) -> tuple[bool, str]:
        if permission == "superadmin":
            return self.config.is_superadmin(sender_id), "超级管理员"
        if permission == "admin":
            return (
                self.config.is_admin(sender_id) or self.config.is_superadmin(sender_id)
            ), "管理员"
        return True, ""

    async def _check_command_rate_limit(
        self,
        rate_limit: CommandRateLimit,
        command_name: str,
        rate_limit_key: str,
        sender_id: int,
        send_message: Callable[[str], Awaitable[None]],
    ) -> bool:
        # 获取 rate_limiter 实例
        limiter = self.rate_limiter
        if limiter is None and hasattr(self.security, "rate_limiter"):
            limiter = self.security.rate_limiter

        if limiter is None:
            logger.warning(
                "[命令] 限流器缺失，跳过限流: cmd=/%s",
                command_name,
            )
            return True

        allowed, remaining = limiter.check_command(
            sender_id, rate_limit_key, rate_limit
        )
        if not allowed:
            if remaining >= 60:
                minutes = remaining // 60
                seconds = remaining % 60
                time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
            else:
                time_str = f"{remaining}秒"

            await send_message(f"⏳ /{command_name} 命令太频繁，请 {time_str}后再试")
            return False

        limiter.record_command(sender_id, rate_limit_key, rate_limit)
        logger.debug(
            "[命令] 动态限流记录成功: cmd=/%s key=%s sender=%s limits=%s",
            command_name,
            rate_limit_key,
            sender_id,
            f"U:{rate_limit.user}/A:{rate_limit.admin}",
        )
        return True

    async def _send_no_permission(
        self,
        sender_id: int,
        cmd_name: str,
        required_role: str,
        send_message: Callable[[str], Awaitable[None]],
    ) -> None:
        logger.warning("[命令] 权限不足: sender=%s cmd=/%s", sender_id, cmd_name)
        await send_message(f"⚠️ 权限不足：只有{required_role}可以使用此命令")
