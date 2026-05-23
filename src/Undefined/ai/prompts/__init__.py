"""Prompt 构建子包。

对外稳定入口：``PromptBuilder``；导入路径 ``Undefined.ai.prompts`` 指向本子包。
"""

# 子包唯一公开类：PromptBuilder
from Undefined.ai.prompts.builder import PromptBuilder

# 子包公开 API
__all__ = ["PromptBuilder"]
