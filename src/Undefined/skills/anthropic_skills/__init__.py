"""Anthropic Agent Skills 注册中心。

自动发现、解析并管理 SKILL.md 格式的 Agent Skills。
遵循 agentskills.io 开放标准，参照 Claude Code 实现。

功能:
- 自动发现指定目录下的 SKILL.md skills
- 为每个 skill 生成 OpenAI function calling schema（注册为可调用 tool）
- 生成 XML 格式的元数据摘要，用于注入 system prompt
- 提供 skill 内容读取（AI 调用 tool 时返回完整正文）
- 支持文件监视热重载
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from Undefined.skills.anthropic_skills.loader import (
    AnthropicSkillItem,
    discover_skills,
)

logger = logging.getLogger(__name__)

# 默认分隔符，与 config.tools_dot_delimiter 保持一致
_DEFAULT_DOT_DELIMITER = "-_-"


class AnthropicSkillRegistry:
    """Anthropic Agent Skills 注册表。

    负责 skill 的自动发现、schema 生成、元数据组装和内容提供。
    独立于 BaseRegistry（后者假定 config.json + handler.py 模式）。
    """

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        dot_delimiter: str = _DEFAULT_DOT_DELIMITER,
    ) -> None:
        """初始化 Anthropic Skills 注册表。

        参数:
            skills_dir: 存放 skills 的根目录。
                        若为 None 则使用默认路径 ``skills/anthropic_skills/``。
                        目录不存在时静默跳过（skills 是可选的）。
            dot_delimiter: 用于替换工具名中 ``.`` 的分隔符，默认 ``-_-``。
                           工具内部命名为 ``skills.<name>``，注册时变为
                           ``skills-_-<name>``。
        """
        if skills_dir is None:
            self.skills_dir = Path(__file__).parent
        else:
            self.skills_dir = Path(skills_dir)

        self.dot_delimiter = dot_delimiter
        self._items: Dict[str, AnthropicSkillItem] = {}
        self._schema_cache: List[Dict[str, Any]] = []

        # 热重载相关
        self._watch_task: Optional[asyncio.Task[None]] = None
        self._watch_stop: Optional[asyncio.Event] = None
        self._last_snapshot: Dict[str, tuple[int, int]] = {}

        # 初始加载
        self.load_skills()

    # ------------------------------------------------------------------
    # 加载与发现
    # ------------------------------------------------------------------

    def load_skills(self) -> None:
        """从 skills_dir 发现并加载所有 Anthropic Skills。"""
        self._items.clear()
        self._schema_cache.clear()

        if not self.skills_dir.exists():
            logger.debug("[AnthropicSkills] 目录不存在，跳过: %s", self.skills_dir)
            return

        items = discover_skills(self.skills_dir)
        for item in items:
            self._items[item.name] = item
            self._schema_cache.append(self._build_tool_schema(item))

        if self._items:
            names = sorted(self._items.keys())
            logger.info(
                "[AnthropicSkills] 加载了 %d 个 skills: %s",
                len(names),
                ", ".join(names),
            )
        else:
            logger.debug("[AnthropicSkills] 未发现任何 skill: %s", self.skills_dir)

    def get_skill(self, name: str) -> Optional[AnthropicSkillItem]:
        """按 name 获取 skill 项。"""
        return self._items.get(name)

    def get_all_skills(self) -> List[AnthropicSkillItem]:
        """返回所有已加载的 skill 项。"""
        return list(self._items.values())

    def has_skills(self) -> bool:
        """是否有已加载的 skills。"""
        return len(self._items) > 0

    # ------------------------------------------------------------------
    # OpenAI Function Calling Schema
    # ------------------------------------------------------------------

    def _build_tool_schema(self, item: AnthropicSkillItem) -> Dict[str, Any]:
        """为 skill 构建 OpenAI function calling 格式的 schema。

        AI 调用此 tool 后将获得该 skill 的完整指令内容。
        """
        tool_name = item.build_tool_name(self.dot_delimiter)
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": (
                    f"[Anthropic Skill] {item.description} "
                    f"调用此工具以获取该 skill 的完整指令和知识内容。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """返回所有 skills 的 OpenAI tool schema 列表。"""
        return list(self._schema_cache)

    # ------------------------------------------------------------------
    # Skill 内容提供（作为 tool 执行结果）
    # ------------------------------------------------------------------

    def read_skill_content(self, name: str) -> str:
        """读取 skill 的完整内容，用于 tool 调用的返回值。

        返回 SKILL.md 正文 + 附带文件列表（如有）。

        参数:
            name: skill 的 name（不含前缀）

        返回:
            格式化的 skill 内容文本
        """
        item = self._items.get(name)
        if item is None:
            logger.warning("[AnthropicSkills] 未找到 skill: %s", name)
            return f"未找到 Anthropic Skill: {name}"

        parts: list[str] = [item.body]

        # 列出附带文件
        files = item.get_file_listing()
        if files:
            file_list = "\n".join(f"  - {f}" for f in files)
            parts.append(
                f"\n\n---\n附带文件（可在后续对话中请求查看详细内容）:\n{file_list}"
            )

        logger.debug(
            "[AnthropicSkills] 读取 skill 内容: name=%s body_len=%d files=%d",
            name,
            len(item.body),
            len(files),
        )
        return "\n".join(parts)

    async def execute_skill_tool(
        self, tool_name: str, _args: Dict[str, Any], _context: Dict[str, Any]
    ) -> str:
        """作为 function tool 的执行入口。

        从 tool_name 中提取 skill name，读取并返回 skill 内容。

        参数:
            tool_name: 完整的 tool 名称（如 ``skills-_-<name>``）
            _args: 调用参数（当前不使用）
            _context: 执行上下文（当前不使用）

        返回:
            skill 的完整内容文本
        """
        # 从 tool_name 中提取 skill name
        # 格式: skills<delimiter><name>，如 skills-_-pdf-processing
        prefix = f"skills{self.dot_delimiter}"
        if tool_name.startswith(prefix):
            skill_name = tool_name[len(prefix) :]
        else:
            skill_name = tool_name

        logger.info(
            "[AnthropicSkills] 执行 skill tool: %s -> %s", tool_name, skill_name
        )
        return self.read_skill_content(skill_name)

    # ------------------------------------------------------------------
    # 元数据 XML 生成（注入 system prompt）
    # ------------------------------------------------------------------

    def build_metadata_xml(self) -> str:
        """生成 XML 格式的 skills 元数据摘要。

        用于注入到 system prompt 中，让 AI 知道哪些 skills 可用。
        遵循 agentskills.io 的推荐格式。

        返回:
            XML 格式字符串，若无 skills 则返回空字符串
        """
        if not self._items:
            return ""

        lines: list[str] = ["<available_skills>"]
        for item in self._items.values():
            tool_name = item.build_tool_name(self.dot_delimiter)
            lines.append("  <skill>")
            lines.append(f"    <name>{_escape_xml(item.name)}</name>")
            lines.append(
                f"    <description>{_escape_xml(item.description)}</description>"
            )
            lines.append(f"    <tool_name>{_escape_xml(tool_name)}</tool_name>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 热重载
    # ------------------------------------------------------------------

    def _compute_snapshot(self) -> Dict[str, tuple[int, int]]:
        """计算 skills 目录下所有 SKILL.md 的文件指纹。"""
        snapshot: Dict[str, tuple[int, int]] = {}
        if not self.skills_dir.exists():
            return snapshot
        for path in self.skills_dir.rglob("SKILL.md"):
            if path.is_file():
                try:
                    stat = path.stat()
                    snapshot[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
                except OSError:
                    continue
        return snapshot

    async def _watch_loop(self, interval: float, debounce: float) -> None:
        """文件监视循环，检测 SKILL.md 变更并重新加载。"""
        self._last_snapshot = self._compute_snapshot()
        last_change = 0.0
        pending = False

        while self._watch_stop and not self._watch_stop.is_set():
            await asyncio.sleep(interval)
            snapshot = self._compute_snapshot()
            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                last_change = time.monotonic()
                pending = True

            if pending and (time.monotonic() - last_change) >= debounce:
                pending = False
                self.load_skills()
                logger.info("[AnthropicSkills] 热重载完成: count=%d", len(self._items))

    def start_hot_reload(self, interval: float = 2.0, debounce: float = 0.5) -> None:
        """启动 SKILL.md 文件监视，支持热重载。"""
        if self._watch_task is not None:
            return
        self._watch_stop = asyncio.Event()
        self._watch_task = asyncio.create_task(self._watch_loop(interval, debounce))
        logger.info(
            "[AnthropicSkills] 热重载已启动: interval=%.2fs debounce=%.2fs",
            interval,
            debounce,
        )

    async def stop_hot_reload(self) -> None:
        """停止文件监视。"""
        if not self._watch_task or not self._watch_stop:
            return
        self._watch_stop.set()
        try:
            await self._watch_task
        finally:
            self._watch_task = None
            self._watch_stop = None
            logger.info("[AnthropicSkills] 热重载已停止")


def _escape_xml(text: str) -> str:
    """简单的 XML 转义。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
