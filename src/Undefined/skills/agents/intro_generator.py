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

logger = logging.getLogger(__name__)


@dataclass
class AgentIntroGenConfig:
    enabled: bool = True
    queue_interval_seconds: float = 1.0
    max_tokens: int = 700
    cache_path: Path = Path(".cache/agent_intro_hashes.json")


class AgentIntroGenerator:
    def __init__(
        self, agents_dir: Path, ai_client: Any, config: AgentIntroGenConfig
    ) -> None:
        self.agents_dir = agents_dir
        self.ai_client = ai_client
        self.config = config
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._cache: dict[str, str] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._prompt_path = Path("res/prompts/agent_intro_generation.txt")

    async def start(self) -> None:
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

    async def _load_cache(self) -> None:
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
        path = self.config.cache_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(self._cache, ensure_ascii=False, indent=2))
        except Exception as e:
            logger.warning(f"[AgentIntro] 保存缓存失败: {e}")

    async def _enqueue_changed_agents(self) -> None:
        for agent_dir in sorted(self.agents_dir.iterdir()):
            if not agent_dir.is_dir() or agent_dir.name.startswith("_"):
                continue
            if not (agent_dir / "config.json").exists():
                continue
            if not (agent_dir / "handler.py").exists():
                continue
            agent_name = agent_dir.name
            digest = self._compute_agent_hash(agent_dir)
            if not digest:
                continue
            if self._cache.get(agent_name) == digest:
                continue
            await self._queue.put(agent_name)
            logger.info(f"[AgentIntro] 检测到变更，排队生成: {agent_name}")

    def _compute_agent_hash(self, agent_dir: Path) -> str:
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
        intro_path = agent_dir / "intro.md"
        prompt_path = agent_dir / "prompt.md"
        config_path = agent_dir / "config.json"
        generated_path = agent_dir / "intro.generated.md"

        intro_text = (
            intro_path.read_text(encoding="utf-8") if intro_path.exists() else ""
        )
        prompt_text = (
            prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
        )
        config_text = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )

        tools_summary = self._summarize_tools(agent_dir / "tools")

        system_prompt = await self._load_system_prompt()

        user_prompt = (
            f"Agent 名称: {agent_name}\n\n"
            "intro.md 内容:\n"
            f"{intro_text.strip()}\n\n"
            "prompt.md 内容(供参考):\n"
            f"{prompt_text.strip()}\n\n"
            "config.json 内容(供参考):\n"
            f"{config_text.strip()}\n\n"
            "工具能力摘要:\n"
            f"{tools_summary}\n\n"
            "请输出补充说明正文："
        )

        result = await self.ai_client.request_model(
            model_config=self.ai_client.agent_config,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=self.config.max_tokens,
            call_type=f"agent_intro:{agent_name}",
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

    async def _load_system_prompt(self) -> str:
        if self._prompt_path.exists():
            try:
                async with aiofiles.open(self._prompt_path, "r", encoding="utf-8") as f:
                    return (await f.read()).strip()
            except Exception as e:
                logger.warning(f"[AgentIntro] 读取提示词失败: {e}")
        return (
            "你是内部的文档写作者，负责给 Agent 生成简洁的“补充说明”。\n"
            "输出将写入 intro.generated.md，并与 intro.md 合并后用于描述。\n"
            "要求：\n"
            "- 只写补充说明，不要重复 intro.md 的内容。\n"
            "- 保持简洁、概括能力与边界，避免“硬流程/步骤清单”。\n"
            "- 不要写工具调用教程，不要逐条罗列工具名。\n"
            "- 允许一定的弹性与空间，不要过度约束。\n"
            "- 使用中文 Markdown，避免一级标题(#)。\n"
        )

    def _summarize_tools(self, tools_dir: Path) -> str:
        if not tools_dir.exists():
            return "无"
        lines: list[str] = []
        for tool_dir in sorted(p for p in tools_dir.iterdir() if p.is_dir()):
            config_path = tool_dir / "config.json"
            if not config_path.exists():
                continue
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            func = data.get("function", {})
            name = func.get("name", tool_dir.name)
            desc = func.get("description", "")
            params = func.get("parameters", {}).get("properties", {})
            param_keys = ", ".join(sorted(params.keys())) if params else "无"
            lines.append(f"- {name}: {desc} (参数: {param_keys})")
        return "\n".join(lines) if lines else "无"
