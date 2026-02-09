"""Anthropic Agent Skills SKILL.md 解析器。

解析 SKILL.md 文件的 YAML frontmatter 和 Markdown body，
遵循 agentskills.io 规范。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# YAML frontmatter 分隔符正则：匹配以 --- 开头和结尾的块
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?\n",
    re.DOTALL,
)

# name 字段校验：小写字母、数字和连字符，不能以连字符开头/结尾，不能连续连字符
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# name 最大长度
_NAME_MAX_LEN = 64

# description 最大长度
_DESC_MAX_LEN = 1024


@dataclass
class AnthropicSkillItem:
    """Anthropic Agent Skill 数据项。

    保存从 SKILL.md 解析出来的元数据和正文内容。
    """

    name: str
    description: str
    skill_dir: Path
    skill_md_path: Path
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_name(self) -> str:
        """生成注册为 function tool 时使用的名称。

        使用 ``skill__`` 前缀避免与现有工具名冲突。
        """
        return f"skill__{self.name}"

    def get_file_listing(self) -> list[str]:
        """列出 skill 目录下除 SKILL.md 以外的附带文件（相对路径）。"""
        files: list[str] = []
        if not self.skill_dir.exists():
            return files
        for path in sorted(self.skill_dir.rglob("*")):
            if path.is_file() and path.name != "SKILL.md":
                try:
                    rel = path.relative_to(self.skill_dir)
                    files.append(str(rel))
                except ValueError:
                    continue
        return files


def _validate_name(name: str) -> bool:
    """校验 skill name 是否符合规范。"""
    if not name or len(name) > _NAME_MAX_LEN:
        return False
    if "--" in name:
        return False
    return bool(_NAME_RE.match(name))


def parse_skill_md(skill_md_path: Path) -> AnthropicSkillItem | None:
    """解析单个 SKILL.md 文件。

    参数:
        skill_md_path: SKILL.md 文件的绝对路径

    返回:
        解析成功返回 AnthropicSkillItem，失败返回 None
    """
    if not skill_md_path.exists():
        logger.debug("SKILL.md 不存在: %s", skill_md_path)
        return None

    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("读取 SKILL.md 失败: %s: %s", skill_md_path, exc)
        return None

    # 解析 frontmatter
    match = _FRONTMATTER_RE.match(content)
    if not match:
        logger.warning("SKILL.md 缺少有效的 YAML frontmatter: %s", skill_md_path)
        return None

    raw_yaml = match.group(1)
    body = content[match.end() :]

    try:
        frontmatter = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        logger.error("SKILL.md frontmatter YAML 解析失败: %s: %s", skill_md_path, exc)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning("SKILL.md frontmatter 不是有效的映射: %s", skill_md_path)
        return None

    # 提取并校验必填字段
    name = str(frontmatter.get("name", "")).strip()
    if not name:
        logger.warning("SKILL.md 缺少 name 字段: %s", skill_md_path)
        return None

    if not _validate_name(name):
        logger.warning(
            "SKILL.md name 不符合规范 (小写字母/数字/连字符, 最大 %d 字符, "
            "不能以连字符开头/结尾, 不能有连续连字符): name=%r path=%s",
            _NAME_MAX_LEN,
            name,
            skill_md_path,
        )
        return None

    description = str(frontmatter.get("description", "")).strip()
    if not description:
        logger.warning("SKILL.md 缺少 description 字段: %s", skill_md_path)
        return None

    if len(description) > _DESC_MAX_LEN:
        logger.warning(
            "SKILL.md description 超过最大长度 %d: len=%d path=%s",
            _DESC_MAX_LEN,
            len(description),
            skill_md_path,
        )
        # 截断但不拒绝
        description = description[:_DESC_MAX_LEN]

    skill_dir = skill_md_path.parent
    return AnthropicSkillItem(
        name=name,
        description=description,
        skill_dir=skill_dir,
        skill_md_path=skill_md_path,
        body=body.strip(),
        frontmatter=frontmatter,
    )


def discover_skills(skills_dir: Path) -> list[AnthropicSkillItem]:
    """从目录中发现并解析所有 Anthropic Skills。

    扫描 skills_dir 下所有直接子目录，查找包含 SKILL.md 的目录。

    参数:
        skills_dir: 要扫描的根目录

    返回:
        成功解析的 AnthropicSkillItem 列表
    """
    if not skills_dir.exists() or not skills_dir.is_dir():
        return []

    items: list[AnthropicSkillItem] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue

        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            logger.debug("目录 %s 下未找到 SKILL.md，跳过", entry)
            continue

        item = parse_skill_md(skill_md)
        if item is None:
            continue

        # 校验 name 是否与目录名一致（规范要求）
        if item.name != entry.name:
            logger.warning(
                "SKILL.md name (%r) 与目录名 (%r) 不一致: %s "
                "(将使用 SKILL.md 中的 name)",
                item.name,
                entry.name,
                skill_md,
            )

        items.append(item)

    return items
