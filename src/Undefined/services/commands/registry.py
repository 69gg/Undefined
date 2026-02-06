from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

CommandHandler = Callable[[list[str], CommandContext], Awaitable[None]]


@dataclass
class CommandMeta:
    """命令元信息。"""

    name: str
    description: str
    usage: str
    example: str
    permission: str
    rate_limit: str
    show_in_help: bool
    order: int
    aliases: list[str]
    handler_path: Path
    module_name: str
    handler: CommandHandler | None = None


class CommandRegistry:
    """基于目录的命令注册表。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._commands: dict[str, CommandMeta] = {}
        self._aliases: dict[str, str] = {}

    def load_commands(self) -> None:
        self._commands.clear()
        self._aliases.clear()

        if not self.base_dir.exists():
            logger.warning("命令目录不存在: %s", self.base_dir)
            return

        logger.info("[CommandRegistry] 开始扫描命令目录: %s", self.base_dir)

        for command_dir in sorted(self.base_dir.iterdir()):
            if not command_dir.is_dir() or command_dir.name.startswith("_"):
                continue
            self._load_command_dir(command_dir)

        command_names = sorted(self._commands.keys())
        logger.info(
            "[CommandRegistry] 已加载 %s 个命令: %s",
            len(command_names),
            ", ".join(command_names),
        )
        if self._aliases:
            alias_pairs = ", ".join(
                f"{alias}->{target}" for alias, target in sorted(self._aliases.items())
            )
            logger.info("[CommandRegistry] 别名映射: %s", alias_pairs)

    def _load_command_dir(self, command_dir: Path) -> None:
        config_path = command_dir / "config.json"
        handler_path = command_dir / "handler.py"
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
                    "services",
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
                module_name=module_name,
            )
            if name in self._commands:
                logger.warning(
                    "[CommandRegistry] 命令名重复，后者覆盖前者: name=%s dir=%s",
                    name,
                    command_dir,
                )
            self._commands[name] = meta
            logger.info(
                "[CommandRegistry] 已注册命令: /%s permission=%s rate_limit=%s aliases=%s",
                meta.name,
                meta.permission,
                meta.rate_limit,
                meta.aliases or "[]",
            )
            for alias in meta.aliases:
                existing = self._aliases.get(alias)
                if existing is not None and existing != name:
                    logger.warning(
                        "[CommandRegistry] 别名冲突，保留首个映射: alias=%s current=%s ignored=%s",
                        alias,
                        existing,
                        name,
                    )
                    continue
                self._aliases[alias] = name
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

    def _normalize_rate_limit(self, value: Any) -> str:
        text = str(value or "default").strip().lower()
        if text in {"none", "default", "stats"}:
            return text
        return "default"

    def _normalize_aliases(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        aliases: list[str] = []
        for item in value:
            alias = str(item).strip().lower()
            if alias:
                aliases.append(alias)
        return aliases

    def resolve(self, command_name: str) -> CommandMeta | None:
        normalized = command_name.strip().lower()
        canonical = self._aliases.get(normalized, normalized)
        if canonical != normalized:
            logger.info(
                "[CommandRegistry] 命令别名解析: /%s -> /%s",
                normalized,
                canonical,
            )
        return self._commands.get(canonical)

    def list_commands(self, *, include_hidden: bool = False) -> list[CommandMeta]:
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
        if command.handler is None:
            command.handler = self._load_handler(command)
        try:
            await command.handler(args, context)
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
        spec = importlib.util.spec_from_file_location(
            command.module_name,
            command.handler_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载命令处理器: {command.handler_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
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
