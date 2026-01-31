import logging
from pathlib import Path
from typing import Dict, Any, List

from Undefined.skills.registry import BaseRegistry
from Undefined.skills.agents.intro_utils import build_agent_description

logger = logging.getLogger(__name__)


class AgentRegistry(BaseRegistry):
    """Agent 注册表，自动发现和加载 agents"""

    def __init__(self, agents_dir: str | Path | None = None):
        if agents_dir is None:
            agents_path = Path(__file__).parent
        else:
            agents_path = Path(agents_dir)

        super().__init__(agents_path, kind="agent")
        self.set_watch_filenames(
            {"config.json", "handler.py", "intro.md", "intro.generated.md"}
        )
        self.set_watch_paths([self.base_dir])
        self.load_agents()

    def load_agents(self) -> None:
        self.load_items()
        self._apply_agent_intros()
        self._log_agents_summary()

    def _log_agents_summary(self) -> None:
        agent_names = list(self._items.keys())
        if agent_names:
            logger.info("=" * 60)
            logger.info("Agent 加载完成统计")
            logger.info(f"  - 已加载 Agents ({len(agent_names)} 个):")
            for name in sorted(agent_names):
                logger.info(f"    * {name}")
            logger.info("=" * 60)

    def get_agents_schema(self) -> List[Dict[str, Any]]:
        return self.get_schema()

    def _apply_agent_intros(self) -> None:
        for name, item in self._items.items():
            agent_dir = self.base_dir / name
            if not agent_dir.exists():
                continue
            description = build_agent_description(
                agent_dir,
                fallback=item.config.get("function", {}).get("description", ""),
            )
            if not description:
                continue
            item.config.setdefault("function", {})
            item.config["function"]["description"] = description

    async def execute_agent(
        self, agent_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        return await self.execute(agent_name, args, context)
