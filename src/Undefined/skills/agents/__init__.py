import logging
from pathlib import Path
from typing import Dict, Any, List

from Undefined.skills.registry import BaseRegistry
from Undefined.skills.agents.intro_utils import build_agent_description

logger = logging.getLogger(__name__)


class AgentRegistry(BaseRegistry):
    """智能体(Agent)注册中心

    自动发现、加载并管理具有独立逻辑和工具集的 Agent 项。
    支持简介(intro)的自动提取和热重载。
    """

    def __init__(self, agents_dir: str | Path | None = None) -> None:
        """初始化 Agent 注册表

        参数:
            agents_dir: Agent 存放的根目录
        """
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
        """执行完整的 Agent 加载流程

        包含项目发现、简介注入以及加载汇总日志记录。
        """
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
        """获取所有 Agent 的架构定义列表"""
        return self.get_schema()

    def _apply_agent_intros(self) -> None:
        """为每个已加载的 Agent 注入自述简介(Description)

        优先从 intro.md 或生成的 md 文件中读取，否则回退到 config 里的描述。
        """
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
            logger.debug("[Agent简介] %s intro_len=%s", name, len(description))

    async def execute_agent(
        self, agent_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """调用并执行特定的 Agent

        参数:
            agent_name: Agent 名称
            args: 调用参数
            context: 执行上下文

        返回:
            Agent 执行结果文本
        """
        return await self.execute(agent_name, args, context)
