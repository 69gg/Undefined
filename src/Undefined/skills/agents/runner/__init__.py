"""Agent runner 子包：context 准备、工具执行与 LLM 迭代循环。"""

# 对外 re-export，兼容 `from Undefined.skills.agents.runner import run_agent_with_tools`
from Undefined.skills.agents.runner.context import load_prompt_text
from Undefined.skills.agents.runner.loop import (
    DEFAULT_AGENT_MAX_ITERATIONS,
    run_agent_with_tools,
)
from Undefined.skills.agents.runner.tools import _filter_tools_for_runtime_config

__all__ = [
    "DEFAULT_AGENT_MAX_ITERATIONS",
    "load_prompt_text",
    "run_agent_with_tools",
    "_filter_tools_for_runtime_config",
]
