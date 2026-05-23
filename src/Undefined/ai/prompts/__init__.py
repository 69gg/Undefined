"""Prompt 构建子包。

对外稳定入口：``PromptBuilder``；旧路径 ``Undefined.ai.prompts`` 通过 shim 保持兼容。
"""

# 子包唯一公开类：PromptBuilder
from Undefined.ai.prompts.builder import PromptBuilder

# 子包公开 API
__all__ = ["PromptBuilder"]
