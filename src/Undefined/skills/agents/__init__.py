"""
Agent Registry - Agent 自动发现和注册系统
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent 注册表，自动发现和加载 agents"""

    def __init__(self, agents_dir: str | Path | None = None):
        if agents_dir is None:
            self.agents_dir = Path(__file__).parent
        else:
            self.agents_dir = Path(agents_dir)

        self._agents_schema: List[Dict[str, Any]] = []
        self._agents_handlers: Dict[str, Any] = {}
        self.load_agents()

    def load_agents(self) -> None:
        """自动发现和加载 agents"""
        self._agents_schema = []
        self._agents_handlers = {}

        if not self.agents_dir.exists():
            logger.warning(f"Agents directory does not exist: {self.agents_dir}")
            return

        for item in self.agents_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._load_agent_from_dir(item)

        agent_names = list(self._agents_handlers.keys())
        logger.info(
            f"Successfully loaded {len(self._agents_schema)} agents: {', '.join(agent_names)}"
        )

    def _load_agent_from_dir(self, agent_dir: Path) -> None:
        """从目录加载单个 agent"""
        config_path = agent_dir / "config.json"
        handler_path = agent_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            return

        import importlib.util

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if "function" not in config or "name" not in config.get("function", {}):
                logger.error(
                    f"Invalid agent config in {agent_dir}: missing function.name"
                )
                return

            agent_name = config["function"]["name"]

            spec = importlib.util.spec_from_file_location(
                f"agents.{agent_name}", handler_path
            )
            if spec is None or spec.loader is None:
                logger.error(f"Failed to load agent handler spec from {handler_path}")
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                logger.error(f"Agent handler in {agent_dir} missing 'execute' function")
                return

            self._agents_schema.append(config)
            self._agents_handlers[agent_name] = module.execute

            logger.debug(f"Loaded agent: {agent_name}")

        except Exception as e:
            logger.error(f"Failed to load agent from {agent_dir}: {e}")

    def get_agents_schema(self) -> List[Dict[str, Any]]:
        """获取所有 agent 的 schema 定义（用于 OpenAI function calling）"""
        return self._agents_schema

    async def execute_agent(
        self, agent_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """执行 agent"""
        handler = self._agents_handlers.get(agent_name)
        if not handler:
            return f"Agent not found: {agent_name}"

        try:
            if hasattr(handler, "__call__"):
                result = await handler(args, context)
                return str(result)
            return f"Invalid handler for agent: {agent_name}"
        except Exception as e:
            logger.exception(f"Error executing agent {agent_name}")
            return f"Error executing agent {agent_name}: {str(e)}"
