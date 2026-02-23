from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

CommandHandler = Callable[[list[str], CommandContext], Awaitable[None]]
CommandSnapshot = tuple[int | None, int | None, int | None]

_COMMAND_CONFIG_FILENAME = "config.json"
_COMMAND_HANDLER_FILENAME = "handler.py"
_COMMAND_DOC_FILENAME = "README.md"
_RELOAD_SCAN_INTERVAL_SECONDS = 0.2


@dataclass
class CommandRateLimit:
    """命令限流规则（单位：秒，0表示无限制）"""

    user: int = 10
    admin: int = 5
    superadmin: int = 0


@dataclass
class CommandMeta:
    """命令元信息。"""

    name: str
    description: str
    usage: str
    example: str
    permission: str
    rate_limit: CommandRateLimit
    show_in_help: bool
    order: int
    aliases: list[str]
    handler_path: Path
    doc_path: Path | None
    module_name: str
    handler: CommandHandler | None = None


class CommandRegistry:
    """基于目录的命令注册表。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._commands: dict[str, CommandMeta] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.RLock()
        self._last_snapshot: dict[str, CommandSnapshot] = {}
        self._last_scan_at = 0.0

    def load_commands(self) -> None:
        with self._lock:
            self._load_commands_locked()
            self._last_snapshot = self._build_snapshot()
            self._last_scan_at = time.monotonic()

    def maybe_reload(self) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_scan_at < _RELOAD_SCAN_INTERVAL_SECONDS:
                return False
            self._last_scan_at = now
            latest_snapshot = self._build_snapshot()
            if latest_snapshot == self._last_snapshot:
                return False
            logger.info("[CommandRegistry] 检测到命令目录变化，开始热重载")
            self._load_commands_locked()
            self._last_snapshot = self._build_snapshot()
            return True

    def _load_commands_locked(self) -> None:
        commands: dict[str, CommandMeta] = {}
        aliases: dict[str, str] = {}
        if not self.base_dir.exists():
            logger.warning("命令目录不存在: %s", self.base_dir)
            self._commands = commands
            self._aliases = aliases
            return

        logger.info("[CommandRegistry] 开始扫描命令目录: %s", self.base_dir)

        for command_dir in sorted(self.base_dir.iterdir()):
            if not command_dir.is_dir() or command_dir.name.startswith("_"):
                continue
            self._load_command_dir(command_dir, commands, aliases)

        self._commands = commands
        self._aliases = aliases

        command_names = sorted(commands.keys())
        logger.info(
            "[CommandRegistry] 已加载 %s 个命令: %s",
            len(command_names),
            ", ".join(command_names),
        )
        if aliases:
            alias_pairs = ", ".join(
                f"{alias}->{target}" for alias, target in sorted(aliases.items())
            )
            logger.info("[CommandRegistry] 别名映射: %s", alias_pairs)

    def _load_command_dir(
        self,
        command_dir: Path,
        commands: dict[str, CommandMeta],
        aliases: dict[str, str],
    ) -> None:
        config_path = command_dir / _COMMAND_CONFIG_FILENAME
        handler_path = command_dir / _COMMAND_HANDLER_FILENAME
        if not config_path.exists() or not handler_path.exists():
            logger.debug(
                "[CommandRegistry] 跳过目录(缺少 config.json 或 handler.py): %s",
                command_dir,
            )
            return

        try:
            config = self._read_config(config_path)
            name = str(config.get("name") or "").strip().lower()
            if not name:
                logger.warning("命令配置缺少 name: %s", config_path)
                return

            module_name = ".".join(
                [
                    "Undefined",
                    "skills",
                    "commands",
                    command_dir.name,
                    "handler",
                ]
            )

            meta = CommandMeta(
                name=name,
                description=str(config.get("description") or "").strip(),
                usage=str(config.get("usage") or f"/{name}").strip(),
                example=str(config.get("example") or "").strip(),
                permission=self._normalize_permission(config.get("permission")),
                rate_limit=self._normalize_rate_limit(config.get("rate_limit")),
                show_in_help=bool(config.get("show_in_help", True)),
                order=int(config.get("order", 999)),
                aliases=self._normalize_aliases(config.get("aliases")),
                handler_path=handler_path,
                doc_path=(command_dir / _COMMAND_DOC_FILENAME)
                if (command_dir / _COMMAND_DOC_FILENAME).exists()
                else None,
                module_name=module_name,
            )
            if name in commands:
                logger.warning(
                    "[CommandRegistry] 命令名重复，后者覆盖前者: name=%s dir=%s",
                    name,
                    command_dir,
                )
            commands[name] = meta
            logger.info(
                "[CommandRegistry] 已注册命令: /%s permission=%s rate_limit=%s aliases=%s",
                meta.name,
                meta.permission,
                f"U:{meta.rate_limit.user}s/A:{meta.rate_limit.admin}s/S:{meta.rate_limit.superadmin}s",
                meta.aliases or "[]",
            )
            for alias in meta.aliases:
                existing = aliases.get(alias)
                if existing is not None and existing != name:
                    logger.warning(
                        "[CommandRegistry] 别名冲突，保留首个映射: alias=%s current=%s ignored=%s",
                        alias,
                        existing,
                        name,
                    )
                    continue
                aliases[alias] = name
        except Exception as exc:
            logger.exception("加载命令目录失败: %s, err=%s", command_dir, exc)

    def _read_config(self, config_path: Path) -> dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"命令配置必须是 JSON 对象: {config_path}")
        return data

    def _normalize_permission(self, value: Any) -> str:
        text = str(value or "public").strip().lower()
        if text in {"public", "admin", "superadmin"}:
            return text
        return "public"

    def _normalize_rate_limit(self, value: Any) -> CommandRateLimit:
        if isinstance(value, dict):
            try:
                return CommandRateLimit(
                    user=int(value.get("user", 10)),
                    admin=int(value.get("admin", 5)),
                    superadmin=int(value.get("superadmin", 0)),
                )
            except (ValueError, TypeError):
                logger.warning(
                    "[CommandRegistry] 命令限流配置解析失败，使用默认值: %s", value
                )
                return CommandRateLimit()

        text = str(value or "default").strip().lower()
        if text == "none":
            return CommandRateLimit(user=0, admin=0, superadmin=0)
        elif text == "stats":
            return CommandRateLimit(user=3600, admin=0, superadmin=0)
        return CommandRateLimit()

    def _normalize_aliases(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        aliases: list[str] = []
        for item in value:
            alias = str(item).strip().lower()
            if alias:
                aliases.append(alias)
        return aliases

    def _build_snapshot(self) -> dict[str, CommandSnapshot]:
        if not self.base_dir.exists():
            return {}
        snapshot: dict[str, CommandSnapshot] = {}
        for command_dir in sorted(self.base_dir.iterdir()):
            if not command_dir.is_dir() or command_dir.name.startswith("_"):
                continue
            snapshot[command_dir.name] = (
                self._read_mtime_ns(command_dir / _COMMAND_CONFIG_FILENAME),
                self._read_mtime_ns(command_dir / _COMMAND_HANDLER_FILENAME),
                self._read_mtime_ns(command_dir / _COMMAND_DOC_FILENAME),
            )
        return snapshot

    def _read_mtime_ns(self, path: Path) -> int | None:
        try:
            stat_result = path.stat()
        except FileNotFoundError:
            return None
        return stat_result.st_mtime_ns

    def resolve(self, command_name: str) -> CommandMeta | None:
        self.maybe_reload()
        normalized = command_name.strip().lower()
        with self._lock:
            canonical = self._aliases.get(normalized, normalized)
            if canonical != normalized:
                logger.info(
                    "[CommandRegistry] 命令别名解析: /%s -> /%s",
                    normalized,
                    canonical,
                )
            return self._commands.get(canonical)

    def list_commands(self, *, include_hidden: bool = False) -> list[CommandMeta]:
        self.maybe_reload()
        with self._lock:
            items = list(self._commands.values())
            if not include_hidden:
                items = [item for item in items if item.show_in_help]
            return sorted(items, key=lambda item: (item.order, item.name))

    async def execute(
        self,
        command: CommandMeta,
        args: list[str],
        context: CommandContext,
    ) -> None:
        start_time = time.perf_counter()
        logger.info(
            "[CommandRegistry] 开始执行命令: /%s group=%s sender=%s args_count=%s",
            command.name,
            context.group_id,
            context.sender_id,
            len(args),
        )
        logger.debug("[CommandRegistry] 命令参数 /%s: %s", command.name, args)
        with self._lock:
            if command.handler is None:
                command.handler = self._load_handler(command)
            handler = command.handler
        if handler is None:
            raise RuntimeError(f"命令处理器加载失败: /{command.name}")
        try:
            await handler(args, context)
            duration = time.perf_counter() - start_time
            logger.info(
                "[CommandRegistry] 命令执行成功: /%s duration=%.3fs",
                command.name,
                duration,
            )
        except Exception:
            duration = time.perf_counter() - start_time
            logger.exception(
                "[CommandRegistry] 命令执行失败: /%s duration=%.3fs",
                command.name,
                duration,
            )
            raise

    def _load_handler(self, command: CommandMeta) -> CommandHandler:
        sys.modules.pop(command.module_name, None)
        module = types.ModuleType(command.module_name)
        module.__file__ = str(command.handler_path)
        module.__package__ = command.module_name.rpartition(".")[0]
        source = command.handler_path.read_text(encoding="utf-8")
        code = compile(source, str(command.handler_path), "exec")
        sys.modules[command.module_name] = module
        try:
            exec(code, module.__dict__)
        except Exception:
            sys.modules.pop(command.module_name, None)
            raise
        execute = getattr(module, "execute", None)
        if execute is None:
            raise RuntimeError(f"命令处理器缺少 execute: {command.handler_path}")
        if not callable(execute):
            raise RuntimeError(f"命令处理器 execute 不可调用: {command.handler_path}")
        if not asyncio.iscoroutinefunction(execute):
            raise RuntimeError(
                f"命令处理器 execute 必须是 async: {command.handler_path}"
            )
        logger.info(
            "[CommandRegistry] 命令处理器已加载: /%s module=%s",
            command.name,
            command.module_name,
        )
        return cast(CommandHandler, execute)
