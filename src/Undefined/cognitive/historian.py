"""后台史官 Worker，轮询队列处理任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PRONOUN_RE = re.compile(
    r"(?<![a-zA-Z])(我|你|他|她|它|他们|她们|它们|这位|那位)(?![a-zA-Z])"
)
_REL_TIME_RE = re.compile(r"(今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近)")
_REL_PLACE_RE = re.compile(r"(这里|那边|本地|当地|这儿|那儿)")

_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_profile",
        "description": "更新用户/群侧写",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "用户/群名称"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "兴趣/技能标签",
                },
                "summary": {"type": "string", "description": "侧写正文（Markdown）"},
            },
            "required": ["name", "tags", "summary"],
        },
    },
}


class HistorianWorker:
    def __init__(
        self,
        job_queue: Any,
        vector_store: Any,
        profile_storage: Any,
        ai_client: Any,
        config_getter: Callable[[], Any],
    ) -> None:
        self._job_queue = job_queue
        self._vector_store = vector_store
        self._profile_storage = profile_storage
        self._ai_client = ai_client
        self._config_getter = config_getter
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task

    async def _poll_loop(self) -> None:
        poll_count = 0
        while not self._stop_event.is_set():
            result = await self._job_queue.dequeue()
            if result:
                job_id, job = result
                try:
                    await self._process_job(job_id, job)
                except Exception as e:
                    logger.error(f"[史官] 任务 {job_id} 处理失败: {e}")
                    await self._job_queue.fail(job_id, str(e))

            poll_count += 1
            config = self._config_getter()
            if (
                config.failed_cleanup_interval > 0
                and poll_count % config.failed_cleanup_interval == 0
            ):
                from Undefined.utils.cache import cleanup_cache_dir

                cleanup_cache_dir(
                    self._job_queue._failed_dir,
                    max_age_seconds=config.failed_max_age_days * 86400,
                    max_files=config.failed_max_files,
                )

            await asyncio.sleep(config.poll_interval_seconds)

    async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
        config = self._config_getter()
        canonical = await self._rewrite(job)

        is_absolute = True
        for attempt in range(config.rewrite_max_retry + 1):
            if not self._check_regex(canonical):
                break
            if attempt < config.rewrite_max_retry:
                canonical = await self._rewrite(job)
            else:
                is_absolute = False
                logger.warning(f"[史官] 任务 {job_id} 绝对化失败，降级写入")

        metadata: dict[str, Any] = {
            "user_id": job.get("user_id", ""),
            "group_id": job.get("group_id", ""),
            "sender_id": job.get("sender_id", ""),
            "request_type": job.get("request_type", ""),
            "timestamp_utc": job.get("timestamp_utc", ""),
            "timestamp_local": job.get("timestamp_local", ""),
            "is_absolute": is_absolute,
        }
        await self._vector_store.upsert_event(job_id, canonical, metadata)

        if job.get("has_new_info"):
            await self._merge_profile(job, canonical, job_id)

        await self._job_queue.complete(job_id)

    def _check_regex(self, text: str) -> bool:
        return bool(
            _PRONOUN_RE.search(text)
            or _REL_TIME_RE.search(text)
            or _REL_PLACE_RE.search(text)
        )

    async def _rewrite(self, job: dict[str, Any]) -> str:
        from Undefined.utils.resources import read_text_resource

        template = read_text_resource("res/prompts/historian_rewrite.md")
        prompt = template.format(
            timestamp_local=job.get("timestamp_local", ""),
            timezone=job.get("timezone", "Asia/Shanghai"),
            user_id=job.get("user_id", ""),
            group_id=job.get("group_id", ""),
            sender_id=job.get("sender_id", ""),
            action_summary=job.get("action_summary", ""),
            new_info=job.get("new_info", ""),
        )
        response = await self._ai_client.request_model(
            model_config=self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            call_type="historian_rewrite",
        )
        return str(response.choices[0].message.content).strip()

    async def _merge_profile(
        self, job: dict[str, Any], canonical: str, event_id: str
    ) -> None:
        import yaml

        entity_type = "group" if job.get("group_id") else "user"
        entity_id = str(
            job.get("group_id") or job.get("user_id") or job.get("sender_id", "")
        )
        if not entity_id:
            return

        current = (
            await self._profile_storage.read_profile(entity_type, entity_id)
            or "（暂无侧写）"
        )

        from Undefined.utils.resources import read_text_resource

        template = read_text_resource("res/prompts/historian_profile_merge.md")
        prompt = template.format(
            current_profile=current,
            canonical_text=canonical,
            new_info=job.get("new_info", ""),
        )

        response = await self._ai_client.request_model(
            model_config=self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_PROFILE_TOOL],
            tool_choice={"type": "function", "function": {"name": "update_profile"}},
            call_type="historian_profile_merge",
        )

        tool_call = response.choices[0].message.tool_calls[0]
        args = json.loads(tool_call.function.arguments)

        frontmatter = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": args.get("name", ""),
            "tags": args.get("tags", []),
            "updated_at": datetime.now().isoformat(),
            "source_event_id": event_id,
        }
        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n{args.get('summary', '')}"

        await self._profile_storage.write_profile(entity_type, entity_id, content)
        await self._vector_store.upsert_profile(
            f"{entity_type}:{entity_id}",
            args.get("summary", ""),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": args.get("name", ""),
            },
        )
