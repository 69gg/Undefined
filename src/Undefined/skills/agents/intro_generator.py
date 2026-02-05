"""Agent 自我介绍生成器。

自动检测 Agent 配置文件的变更，并使用 AI 生成或更新自我介绍文档。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiofiles

from Undefined.utils.resources import read_text_resource

logger = logging.getLogger(__name__)


@dataclass
class AgentIntroGenConfig:
    """Agent 自我介绍生成器配置。"""

    enabled: bool = True  # 是否启用自动生成
    queue_interval_seconds: float = 1.0  # 队列处理间隔（秒）
    max_tokens: int = 700  # 生成介绍的最大 token 数
    cache_path: Path = Path(".cache/agent_intro_hashes.json")  # 缓存文件路径


class AgentIntroGenerator:
    """Agent 自我介绍生成器。

    监控 Agent 目录，当检测到配置变更时，自动生成或更新自我介绍文档。
    """

    def __init__(
        self, agents_dir: Path, ai_client: Any, config: AgentIntroGenConfig
    ) -> None:
        """初始化 Agent 自我介绍生成器。

        Args:
            agents_dir: Agent 目录路径
            ai_client: AI 客户端
            config: 生成器配置
        """
        self.agents_dir = agents_dir
        self.ai_client = ai_client
        self.config = config
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._cache: dict[str, str] = {}
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动生成器。

        加载缓存，检测变更的 Agent 并加入处理队列。
        """
        if not self.config.enabled:
            logger.info("[AgentIntro] 自动生成已关闭")
            return

        await self._load_cache()
        await self._enqueue_changed_agents()

        if self._queue.empty():
            logger.info("[AgentIntro] 启动时无需要更新的 Agent")
            return

        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """停止生成器后台任务（若存在）。"""
        task = self._worker_task
        if task is None:
            return
        if task.done():
            self._worker_task = None
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("[AgentIntro] 停止时捕获异常: %s", exc)
        finally:
            self._worker_task = None

    async def _load_cache(self) -> None:
        """加载 Agent 哈希缓存。"""
        path = self.config.cache_path
        try:
            if path.exists():
                async with aiofiles.open(path, "r", encoding="utf-8") as f:
                    data = await f.read()
                self._cache = json.loads(data) if data else {}
        except Exception as e:
            logger.warning(f"[AgentIntro] 读取缓存失败: {e}")
            self._cache = {}

    async def _save_cache(self) -> None:
        """保存 Agent 哈希缓存。"""
        path = self.config.cache_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(self._cache, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"[AgentIntro] 保存缓存失败: {e}")

    async def _enqueue_changed_agents(self) -> None:
        """检测变更的 Agent 并加入处理队列。"""
        for agent_dir in sorted(self.agents_dir.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            if not (agent_dir / "config.json").exists():
                continue
            if not (agent_dir / "handler.py").exists():
                continue
            agent_name = agent_dir.name
            generated_path = agent_dir / "intro.generated.md"
            digest = self._compute_agent_hash(agent_dir)
            if not digest:
                continue
            if self._cache.get(agent_name) == digest and generated_path.exists():
                continue
            await self._queue.put(agent_name)
            if generated_path.exists():
                logger.info(f"[AgentIntro] 检测到变更，排队生成: {agent_name}")
            else:
                logger.info(
                    f"[AgentIntro] intro.generated.md 缺失，排队生成: {agent_name}"
                )

    def _compute_agent_hash(self, agent_dir: Path) -> str:
        """计算 Agent 目录的哈希值。

        Args:
            agent_dir: Agent 目录路径

        Returns:
            哈希值字符串
        """
        hasher = hashlib.sha256()
        for path in sorted(self._iter_hash_files(agent_dir)):
            rel = str(path.relative_to(agent_dir)).replace("\\", "/")
            try:
                data = path.read_bytes()
            except OSError:
                continue
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            hasher.update(data)
            hasher.update(b"\0")
        return hasher.hexdigest()

    def _iter_hash_files(self, agent_dir: Path) -> list[Path]:
        """迭代需要计算哈希的文件。

        Args:
            agent_dir: Agent 目录路径

        Returns:
            文件路径列表
        """
        files: list[Path] = []
        for path in agent_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.name in {"intro.md", "intro.generated.md"}:
                continue
            if path.suffix == ".py" or path.name == "config.json":
                files.append(path)
        return files

    async def _worker_loop(self) -> None:
        """工作循环，处理队列中的 Agent。"""
        while True:
            agent_name = await self._queue.get()
            agent_dir = self.agents_dir / agent_name
            try:
                await self._generate_for_agent(agent_name, agent_dir)
                digest = self._compute_agent_hash(agent_dir)
                if digest:
                    self._cache[agent_name] = digest
                    await self._save_cache()
            except Exception as e:
                logger.warning(f"[AgentIntro] 生成失败: {agent_name} -> {e}")
            finally:
                await asyncio.sleep(self.config.queue_interval_seconds)
                self._queue.task_done()

            if self._queue.empty():
                logger.info("[AgentIntro] 启动队列处理完成")
                break

    async def _generate_for_agent(self, agent_name: str, agent_dir: Path) -> None:
        """为指定 Agent 生成自我介绍。

        Args:
            agent_name: Agent 名称
            agent_dir: Agent 目录路径
        """
        prompt_path = agent_dir / "prompt.md"
        generated_path = agent_dir / "intro.generated.md"

        agent_system_prompt = (
            prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        )

        user_prompt = await self._load_intro_prompt()

        result = await self.ai_client.request_model(
            model_config=self.ai_client.agent_config,
            messages=[
                {"role": "system", "content": agent_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self.config.max_tokens,
            call_type=f"agent:{agent_name}",
        )

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = content.strip()
        if not content:
            logger.warning(f"[AgentIntro] 生成内容为空: {agent_name}")
            return

        tmp_path = generated_path.with_suffix(".generated.tmp")
        async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
            await f.write(content + "\n")
        os.replace(tmp_path, generated_path)
        logger.info(f"[AgentIntro] 已更新: {generated_path}")

    async def _load_intro_prompt(self) -> str:
        """加载自我介绍提示词模板。

        Returns:
            提示词字符串
        """
        try:
            return read_text_resource("res/prompts/agent_self_intro.txt").strip()
        except Exception as exc:
            logger.warning(f"[AgentIntro] 读取提示词失败: {exc}")
        return "请作下自我介绍（第一人称）。"

    def _extract_tool_info(self, tool_dir: Path) -> dict[str, Any] | None:
        """从工具目录提取工具信息。

        Args:
            tool_dir: 工具目录路径

        Returns:
            工具信息字典，失败时返回 None
        """
        config_path = tool_dir / "config.json"
        if not config_path.exists():
            return None

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return None

        func = data.get("function", {})
        name = func.get("name", tool_dir.name)
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        param_keys = ", ".join(sorted(params.keys())) if params else "无"

        return {"name": name, "desc": desc, "param_keys": param_keys}

    def _format_tool_info(self, tool_info: dict[str, Any]) -> str:
        """格式化工具信息为字符串。

        Args:
            tool_info: 工具信息字典

        Returns:
            格式化后的字符串
        """
        return f"- {tool_info['name']}: {tool_info['desc']} (参数: {tool_info['param_keys']})"

    def _summarize_tools(self, tools_dir: Path) -> str:
        """生成工具目录的摘要信息。

        Args:
            tools_dir: 工具目录路径

        Returns:
            工具摘要字符串
        """
        if not tools_dir.exists():
            return "无"

        # 获取所有工具目录
        tool_dirs = sorted(p for p in tools_dir.iterdir() if p.is_dir())

        # 提取工具信息
        tool_infos: list[dict[str, Any]] = []
        for tool_dir in tool_dirs:
            tool_info = self._extract_tool_info(tool_dir)
            if tool_info:
                tool_infos.append(tool_info)

        # 格式化工具信息
        lines = [self._format_tool_info(info) for info in tool_infos]

        return "\n".join(lines) if lines else "无"
