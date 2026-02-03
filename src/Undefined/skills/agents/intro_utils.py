"""Agent 自我介绍工具。

提供构建 Agent 描述的工具函数，合并手动编写和自动生成的自我介绍。
"""

from __future__ import annotations

from pathlib import Path


def _read_text(path: Path) -> str:
    """读取文本文件内容。

    Args:
        path: 文件路径

    Returns:
        文件内容（去除首尾空白），读取失败时返回空字符串
    """
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_agent_description(agent_dir: Path, fallback: str = "") -> str:
    """构建 Agent 描述。

    合并手动编写的手册介绍（intro.md）和自动生成的自我介绍（intro.generated.md）。

    优先级：
    1. 如果两者都存在，合并在一起
    2. 如果只有 intro.generated.md 存在，使用它
    3. 如果只有 intro.md 存在，使用它
    4. 如果都不存在，使用 fallback 文本

    Args:
        agent_dir: Agent 目录路径
        fallback: 当没有任何介绍时的回退文本

    Returns:
        合并后的 Agent 描述
    """
    intro_path = agent_dir / "intro.md"
    generated_path = agent_dir / "intro.generated.md"

    # 读取两个介绍文件
    intro_text = _read_text(intro_path)
    generated_text = _read_text(generated_path)

    # 如果两者都为空，返回回退文本
    if not intro_text and not generated_text:
        return fallback.strip()

    # 如果有自动生成的介绍，合并两者
    if generated_text:
        merged = intro_text.rstrip()
        if merged:
            merged += "\n\n---\n\n## 以下为Agent自我介绍\n\n"
        merged += generated_text.strip()
        return merged.strip()

    # 只使用手动编写的介绍
    return intro_text.strip()
