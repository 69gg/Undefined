import logging
from pathlib import Path
from typing import Dict, Any, List

from ..registry import BaseRegistry

logger = logging.getLogger(__name__)


class AgentRegistry(BaseRegistry):
    """Agent 注册表，自动发现和加载 agents"""

    def __init__(self, agents_dir: str | Path | None = None):
        if agents_dir is None:
            agents_path = Path(__file__).parent
        else:
            agents_path = Path(agents_dir)

        super().__init__(agents_path)
        self.load_agents()

    def load_agents(self) -> None:
        """自动发现和加载 agents"""
        self.load_items()

    def get_agents_schema(self) -> List[Dict[str, Any]]:
        """获取所有 agent 的 schema 定义（用于 OpenAI function calling）"""
        return self.get_schema()

    async def execute_agent(
        self, agent_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """执行 agent"""
        return await self.execute(agent_name, args, context)
