"""HistorianWorker 实现。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Coroutine
from datetime import datetime, timezone, tzinfo
from functools import partial
from typing import Any, Callable

from Undefined.ai.transports.openai_transport import RESPONSES_OUTPUT_ITEMS_KEY
from Undefined.cognitive.chroma_scheduler import (
    CHROMA_PRIORITY_BACKGROUND,
    CHROMA_PRIORITY_MAINTENANCE,
)
from Undefined.cognitive.service.helpers import (
    _build_profile_vector_payload,
    _profile_section_error,
    _serialize_profile_markdown,
)
from Undefined.cognitive.vector_store_compat import call_vector_store_method
from Undefined.config.models import HISTORIAN_MIN_POLL_INTERVAL_SECONDS
from Undefined.cognitive.job_queue import QueuedJob
from Undefined.cognitive.historian.scheduling import (
    EntityKey,
    HistorianProgress,
    observations,
    resolve_profile_targets,
    select_ready_phase,
    target_key,
)
from Undefined.utils.tool_calls import extract_required_tool_call_arguments
from Undefined.utils.io import run_cancellation_safe

from Undefined.cognitive.historian.helpers import (
    _coerce_bool,
    _escape_braces,
    _extract_frontmatter_name,
    _extract_frontmatter_updated_at,
    _now_in_job_timezone,
    _preview_text,
    _resolve_timestamp_epoch,
)
from Undefined.cognitive.historian.tools import (
    _PROFILE_TOOL,
    _READ_PROFILE_TOOL,
    _REWRITE_TOOL,
)

logger = logging.getLogger(__name__)


class HistorianWorker:
    def __init__(
        self,
        job_queue: Any,
        vector_store: Any,
        profile_storage: Any,
        ai_client: Any,
        config_getter: Callable[[], Any],
        model_config: Any = None,
        max_concurrency: int = 4,
    ) -> None:
        self._job_queue = job_queue
        self._vector_store = vector_store
        self._profile_storage = profile_storage
        self._ai_client = ai_client
        self._config_getter = config_getter
        self._model_config = model_config
        self._max_concurrency = max(1, int(max_concurrency))
        # max_concurrency 仅在启动时读取一次，热更新不生效；若将来开放热更新，
        # 必须同步更新在途门控（_poll_loop 比较的 _max_concurrency）
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._inflight_tasks: set[asyncio.Task[None]] = set()
        self._active_jobs: dict[str, EntityKey | None] = {}
        self._wakeup = asyncio.Event()

    async def _prepare_query_embedding(self, query_text: str) -> list[float] | None:
        embed_query = getattr(self._vector_store, "embed_query", None)
        if not callable(embed_query):
            return None
        try:
            result = await embed_query(query_text)
        except Exception as exc:
            logger.warning("[史官] 预生成查询向量失败，回退即时计算: error=%s", exc)
            return None
        if not isinstance(result, list):
            logger.warning("[史官] 预生成查询向量返回值非法，回退即时计算")
            return None
        normalized: list[float] = []
        for item in result:
            try:
                normalized.append(float(item))
            except (TypeError, ValueError):
                logger.warning("[史官] 预生成查询向量包含非法元素，回退即时计算")
                return None
        return normalized

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        logger.info("[史官] Worker 启动中")
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[史官] Worker 已启动")

    async def stop(self) -> None:
        logger.info("[史官] Worker 停止中")
        self._stop_event.set()
        self._wakeup.set()
        if self._task:
            await self._task
        logger.info("[史官] Worker 已停止")

    def _phase_finished(self, job_id: str, task: asyncio.Task[None]) -> None:
        self._inflight_tasks.discard(task)
        self._active_jobs.pop(job_id, None)
        self._wakeup.set()
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error(
                "[史官] 阶段未能收敛，保留 processing 等待恢复: job_id=%s error=%s",
                job_id,
                error,
            )

    async def _poll_loop(self) -> None:
        dispatch_count = 0
        try:
            while not self._stop_event.is_set():
                self._wakeup.clear()
                config = self._config_getter()
                poll_interval = max(
                    HISTORIAN_MIN_POLL_INTERVAL_SECONDS,
                    float(config.poll_interval_seconds),
                )
                try:
                    await self._job_queue.recover_stale(
                        config.stale_job_timeout_seconds,
                        exclude_job_ids=self._active_jobs,
                    )
                    if len(self._inflight_tasks) < self._max_concurrency:
                        entries: list[QueuedJob] = await self._job_queue.list_jobs()
                        ready = select_ready_phase(entries, self._active_jobs)
                        if ready is not None:
                            claimed = await self._job_queue.claim(ready.entry.job_id)
                            if claimed is not None:
                                job_id, job = claimed
                                self._active_jobs[job_id] = (
                                    target_key(ready.target) if ready.target else None
                                )
                                task = asyncio.create_task(
                                    self._process_job_with_retry(
                                        job_id, job, target=ready.target
                                    ),
                                    name=f"historian:{job_id}",
                                )
                                self._inflight_tasks.add(task)
                                task.add_done_callback(
                                    partial(self._phase_finished, job_id)
                                )
                                dispatch_count += 1
                                logger.info(
                                    "[史官] 阶段发车: job_id=%s target=%s inflight=%s",
                                    job_id,
                                    self._active_jobs[job_id],
                                    len(self._inflight_tasks),
                                )
                                if (
                                    config.failed_cleanup_interval > 0
                                    and dispatch_count % config.failed_cleanup_interval
                                    == 0
                                ):
                                    from Undefined.utils.cache import cleanup_cache_dir

                                    await asyncio.to_thread(
                                        cleanup_cache_dir,
                                        self._job_queue._failed_dir,
                                        max_age_seconds=config.failed_max_age_days
                                        * 86400,
                                        max_files=config.failed_max_files,
                                    )
                                continue
                except Exception:
                    logger.exception("[史官] 阶段调度失败，保留队列状态等待重试")
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=poll_interval)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            # 轮询在进入收尾 gather 前被取消时，也要取消正在等待模型的阶段。
            for task in self._inflight_tasks:
                task.cancel()
            raise
        finally:
            # 正常停止等待阶段结束；取消时只等待已开始的提交临界区收敛。
            if self._inflight_tasks:
                await asyncio.gather(
                    *list(self._inflight_tasks), return_exceptions=True
                )

    async def _process_job_with_retry(
        self, job_id: str, job: dict[str, Any], *, target: dict[str, str] | None = None
    ) -> None:
        # 模型调用可取消；磁盘/向量提交在各自的临界区内保护。
        await self._execute_phase(job_id, job, target)

    async def _execute_phase(
        self, job_id: str, job: dict[str, Any], target: dict[str, str] | None
    ) -> None:
        try:
            if target is None:
                await self._process_job(job_id, job)
            else:
                progress = HistorianProgress.from_job(job)
                await self._merge_profiles(
                    job,
                    "\n".join(progress.rewrites),
                    job_id,
                    target=target,
                    progress=progress,
                )
                await self._finish_phase(job_id, job, progress)
        except Exception as error:
            retry_count = int(job.get("_retry_count", 0))
            max_retries = self._config_getter().job_max_retries
            if retry_count < max_retries:
                logger.warning(
                    "[史官] 阶段失败，保留顺位重试: job_id=%s retry=%s/%s error=%s",
                    job_id,
                    retry_count + 1,
                    max_retries,
                    error,
                )
                await run_cancellation_safe(self._job_queue.requeue(job_id, str(error)))
            else:
                await run_cancellation_safe(self._job_queue.fail(job_id, str(error)))

    async def _finish_phase(
        self, job_id: str, job: dict[str, Any], progress: HistorianProgress
    ) -> None:
        if progress.pending_targets(job):
            await run_cancellation_safe(self._job_queue.release(job_id))
        else:
            await run_cancellation_safe(self._job_queue.complete(job_id))

    async def _rewrite_and_validate(self, job: dict[str, Any], job_id: str) -> str:
        """改写为绝对化事件文本。"""
        canonical = await self._rewrite(job, job_id=job_id)
        return canonical

    async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
        logger.info(
            "[史官] 开始处理任务 %s: user=%s group=%s sender=%s perspective=%s has_observations=%s profile_targets=%s",
            job_id,
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
            job.get("perspective", ""),
            job.get("has_observations", job.get("has_new_info", False)),
            len(job.get("profile_targets", []) or []),
        )

        observation_items = observations(job)
        progress = HistorianProgress.from_job(job)

        base_metadata: dict[str, Any] = {
            "request_id": job.get("request_id", ""),
            "end_seq": job.get("end_seq", 0),
            "user_id": job.get("user_id", ""),
            "group_id": job.get("group_id", ""),
            "sender_id": job.get("sender_id", ""),
            "request_type": job.get("request_type", ""),
            "timestamp_utc": job.get("timestamp_utc", ""),
            "timestamp_local": job.get("timestamp_local", ""),
            "timestamp_epoch": _resolve_timestamp_epoch(job),
            "timezone": job.get("timezone", ""),
            "location_abs": job.get("location_abs", ""),
            "message_ids": job.get("message_ids", []),
            "perspective": str(job.get("perspective", "")).strip(),
            "schema_version": job.get("schema_version", "final_v1"),
        }

        for idx in range(progress.events_written, len(observation_items)):
            event_id = f"{job_id}_{idx}" if len(observation_items) > 1 else job_id
            if idx >= len(progress.rewrites):
                canonical = await self._rewrite_and_validate(
                    {**job, "observations": observation_items[idx]}, event_id
                )
                progress.rewrites.append(canonical)
                progress.store(job)
                await run_cancellation_safe(self._job_queue.checkpoint(job_id, job))

            # 重试使用相同事件 ID 和已保存的改写，不重复调用模型改写。
            async def commit_event() -> None:
                await call_vector_store_method(
                    self._vector_store.upsert_event,
                    event_id,
                    progress.rewrites[idx],
                    {**base_metadata, "has_observations": True},
                    priority=CHROMA_PRIORITY_BACKGROUND,
                )
                progress.events_written = idx + 1
                progress.store(job)
                await self._job_queue.checkpoint(job_id, job)

            await run_cancellation_safe(commit_event())
        await self._finish_phase(job_id, job, progress)

    def _extract_required_tool_args(
        self,
        response: dict[str, Any],
        *,
        expected_tool_name: str,
        stage: str,
        job_id: str,
        attempt: int | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        suffix = f" stage={stage} expected_tool={expected_tool_name}"
        if attempt is not None:
            suffix += f" attempt={attempt}"
        if target:
            suffix += f" target={target}"
        try:
            return extract_required_tool_call_arguments(
                response,
                expected_tool_name=expected_tool_name,
                stage=stage,
                logger=logger,
                error_context=f"job_id={job_id}{suffix}",
            )
        except Exception as exc:
            logger.error(
                "[史官] 任务 %s 提取工具参数失败:%s err=%s", job_id, suffix, exc
            )
            raise

    async def _rewrite(
        self,
        job: dict[str, Any],
        *,
        job_id: str = "",
    ) -> str:
        from Undefined.utils.resources import read_text_resource

        memo = str(job.get("memo") if "memo" in job else job.get("action_summary", ""))
        observations = str(
            job.get("observations")
            if "observations" in job
            else job.get("new_info", "")
        )
        message_ids_raw = job.get("message_ids", [])
        if isinstance(message_ids_raw, list):
            message_ids = [
                str(item).strip() for item in message_ids_raw if str(item).strip()
            ]
        else:
            message_ids = []
        profile_targets_raw = job.get("profile_targets", [])
        profile_targets_text = "[]"
        if isinstance(profile_targets_raw, list) and profile_targets_raw:
            compact_targets: list[str] = []
            for target in profile_targets_raw:
                if not isinstance(target, dict):
                    continue
                entity_type = str(target.get("entity_type", "")).strip()
                entity_id = str(target.get("entity_id", "")).strip()
                perspective = str(target.get("perspective", "")).strip()
                if not entity_type or not entity_id:
                    continue
                if perspective:
                    compact_targets.append(f"{entity_type}:{entity_id}({perspective})")
                else:
                    compact_targets.append(f"{entity_type}:{entity_id}")
            if compact_targets:
                profile_targets_text = ", ".join(compact_targets)
        logger.debug(
            "[史官] 任务 %s 发起绝对化改写: memo_len=%s observations_len=%s",
            job_id or "unknown",
            len(memo),
            len(observations),
        )

        template = read_text_resource("res/prompts/historian_rewrite.md")
        source_message = str(job.get("source_message", "")).strip()
        recent_messages_raw = job.get("recent_messages", [])
        recent_messages: list[str] = []
        if isinstance(recent_messages_raw, list):
            recent_messages = [
                str(item).strip() for item in recent_messages_raw if str(item).strip()
            ]
        recent_messages_text = "\n---\n".join(recent_messages)
        prompt = template.format(
            request_id=job.get("request_id", ""),
            end_seq=job.get("end_seq", 0),
            timestamp_local=job.get("timestamp_local", ""),
            timezone=job.get("timezone", "Asia/Shanghai"),
            bot_name=job.get("bot_name", "Undefined"),
            user_id=job.get("user_id", ""),
            group_id=job.get("group_id", ""),
            sender_id=job.get("sender_id", ""),
            sender_name=job.get("sender_name", ""),
            group_name=job.get("group_name", ""),
            message_ids=", ".join(message_ids) if message_ids else "[]",
            perspective=job.get("perspective", ""),
            profile_targets=profile_targets_text,
            force="true" if _coerce_bool(job.get("force", False)) else "false",
            action_summary=memo,
            new_info=observations,
            memo=memo,
            observations=observations,
            source_message=source_message or "（无）",
            recent_messages=recent_messages_text or "（无）",
        )
        response = await self._ai_client.submit_background_llm_call(
            model_config=self._model_config or self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_REWRITE_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_rewrite"}},
            call_type="historian_rewrite",
        )
        args = self._extract_required_tool_args(
            response=response,
            expected_tool_name="submit_rewrite",
            stage="historian_rewrite",
            job_id=job_id or "unknown",
        )

        text = str(args.get("text", "")).strip()
        logger.debug(
            "[史官] 任务 %s 收到改写结果: len=%s preview=%s",
            job_id or "unknown",
            len(text),
            _preview_text(text),
        )
        return text

    def _resolve_profile_targets(self, job: dict[str, Any]) -> list[dict[str, str]]:
        return resolve_profile_targets(job)

    async def _merge_profiles(
        self,
        job: dict[str, Any],
        canonical: str,
        event_id: str,
        *,
        target: dict[str, str] | None = None,
        progress: HistorianProgress | None = None,
    ) -> None:
        targets = [target] if target is not None else self._resolve_profile_targets(job)
        for index, current in enumerate(targets, start=1):
            # 顺位由调度器保证；实体锁同时隔离昵称刷新和人工恢复。
            async with self._profile_merge_guard(current):
                await self._merge_profile_target(
                    job=job,
                    canonical=canonical,
                    event_id=event_id,
                    target=current,
                    target_index=index,
                    target_count=len(targets),
                    progress=progress,
                )

    async def _commit_profile_target(
        self,
        job: dict[str, Any],
        event_id: str,
        target: dict[str, str],
        progress: HistorianProgress | None,
        write: Coroutine[Any, Any, None] | None = None,
    ) -> None:
        """侧写文件、向量与目标进度作为同一个取消保护区提交。"""
        if write is not None:
            await write
        if progress is not None:
            progress.finish_target(target)
            progress.store(job)
            await self._job_queue.checkpoint(event_id, job)

    def _profile_merge_guard(self, target: dict[str, str]) -> Any:
        """返回目标实体的合并互斥锁；存储层未提供时退化为无锁上下文。"""
        guard = getattr(self._profile_storage, "merge_guard", None)
        if not callable(guard):
            return contextlib.nullcontext()
        entity_type = str(target.get("entity_type", ""))
        entity_id = str(target.get("entity_id", ""))
        if not entity_type or not entity_id:
            return contextlib.nullcontext()
        return guard(entity_type, entity_id)

    async def _write_profile(
        self,
        *,
        entity_type: str,
        entity_id: str,
        effective_name: str,
        tags: list[str],
        summary: str,
        evaluation: str,
        roast: str,
        event_id: str,
        perspective: str,
        now_timezone: tzinfo | None = None,
    ) -> None:
        instant = datetime.now(timezone.utc)
        if now_timezone is not None:
            stamped = instant.astimezone(now_timezone)
        else:
            stamped = instant.astimezone()
        frontmatter: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": effective_name,
            "tags": tags,
            "updated_at": stamped.isoformat(),
            "source_event_id": event_id,
        }
        if entity_type == "user":
            frontmatter["nickname"] = effective_name
            frontmatter["qq"] = entity_id
        else:
            frontmatter["group_name"] = effective_name
            frontmatter["group_id"] = entity_id
        content = _serialize_profile_markdown(
            frontmatter, summary, evaluation=evaluation, roast=roast
        )

        await self._profile_storage.write_profile(entity_type, entity_id, content)
        logger.info(
            "[史官] 任务 %s 侧写文件写入完成: entity_type=%s entity_id=%s tags=%s perspective=%s",
            event_id,
            entity_type,
            entity_id,
            tags,
            perspective,
        )

        profile_doc, profile_metadata = _build_profile_vector_payload(
            entity_type=entity_type,
            entity_id=entity_id,
            effective_name=effective_name,
            tags=tags,
            summary=summary,
            evaluation=evaluation,
            roast=roast,
        )

        await call_vector_store_method(
            self._vector_store.upsert_profile,
            f"{entity_type}:{entity_id}",
            profile_doc,
            profile_metadata,
            priority=CHROMA_PRIORITY_BACKGROUND,
        )
        logger.info(
            "[史官] 任务 %s 侧写向量入库完成: profile_id=%s perspective=%s",
            event_id,
            f"{entity_type}:{entity_id}",
            perspective,
        )

    @staticmethod
    def _historical_event_dedupe_key(
        event: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return (
            str(event.get("document", "")).strip(),
            str(metadata.get("timestamp_local", "")).strip(),
            str(metadata.get("sender_id", "")).strip(),
            str(metadata.get("user_id", "")).strip(),
            str(metadata.get("group_id", "")).strip(),
        )

    async def _query_user_history_events_for_profile_merge(
        self,
        *,
        query_text: str,
        entity_id: str,
        top_k: int,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """用户历史检索兼容路径：分别按 sender_id/user_id 查询并合并去重。

        Compatibility path for user history retrieval:
        query sender_id/user_id separately, then merge and dedupe.
        """
        safe_top_k = max(1, int(top_k))
        query_embedding_value = query_embedding
        if query_embedding_value is None:
            query_embedding_value = await self._prepare_query_embedding(query_text)
        sender_query = call_vector_store_method(
            self._vector_store.query_events,
            query_text,
            priority=CHROMA_PRIORITY_MAINTENANCE,
            top_k=safe_top_k,
            where={"sender_id": entity_id},
            apply_mmr=True,
            query_embedding=query_embedding_value,
        )
        user_query = call_vector_store_method(
            self._vector_store.query_events,
            query_text,
            priority=CHROMA_PRIORITY_MAINTENANCE,
            top_k=safe_top_k,
            where={"user_id": entity_id},
            apply_mmr=True,
            query_embedding=query_embedding_value,
        )
        sender_events_raw, user_events_raw = await asyncio.gather(
            sender_query, user_query
        )
        merged_events = list(sender_events_raw) + list(user_events_raw)

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for event in merged_events:
            key = self._historical_event_dedupe_key(event)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
            if len(deduped) >= safe_top_k:
                break
        return deduped

    async def _merge_profile_target(
        self,
        *,
        job: dict[str, Any],
        canonical: str,
        event_id: str,
        target: dict[str, str],
        target_index: int,
        target_count: int,
        progress: HistorianProgress | None = None,
    ) -> bool:
        entity_type = str(target.get("entity_type", "")).strip()
        entity_id = str(target.get("entity_id", "")).strip()
        perspective = str(target.get("perspective", "")).strip()
        if entity_type not in {"user", "group"} or not entity_id:
            logger.warning(
                "[史官] 任务 %s 侧写目标非法，跳过: target=%s",
                event_id,
                target,
            )
            return False
        logger.info(
            "[史官] 任务 %s 合并侧写目标(%s/%s): entity_type=%s entity_id=%s perspective=%s",
            event_id,
            target_index,
            target_count,
            entity_type,
            entity_id,
            perspective,
        )

        preferred_name = str(target.get("preferred_name", "")).strip()

        observations_raw = job.get("observations", job.get("new_info", []))
        observations_text = (
            "\n".join(observations_raw)
            if isinstance(observations_raw, list)
            else str(observations_raw)
        )
        query_embedding = await self._prepare_query_embedding(observations_text)
        if entity_type == "group":
            historical_events = await call_vector_store_method(
                self._vector_store.query_events,
                observations_text,
                priority=CHROMA_PRIORITY_MAINTENANCE,
                top_k=8,
                where={"group_id": entity_id},
                apply_mmr=True,
                query_embedding=query_embedding,
            )
        else:
            historical_events = await self._query_user_history_events_for_profile_merge(
                query_text=observations_text,
                entity_id=entity_id,
                top_k=8,
                query_embedding=query_embedding,
            )
        historical_lines = (
            "\n".join(
                f"- [{e['metadata'].get('timestamp_local', '')}] {e['document']}"
                for e in historical_events
            )
            or "（暂无历史事件）"
        )

        now_local_dt, now_utc_dt, timezone_label = _now_in_job_timezone(job)
        now_local = now_local_dt.isoformat()
        now_utc = now_utc_dt.isoformat()

        existing_profile = await self._profile_storage.read_profile(
            entity_type, entity_id
        )
        profile_snapshot = (
            existing_profile if existing_profile is not None else "（暂无侧写）"
        )
        profile_updated_at = (
            _extract_frontmatter_updated_at(existing_profile or "") or "（暂无/未知）"
        )

        from Undefined.utils.resources import read_text_resource

        template = read_text_resource("res/prompts/historian_profile_merge.md")
        message_ids_raw = job.get("message_ids", [])
        if isinstance(message_ids_raw, list):
            message_ids = [
                str(item).strip() for item in message_ids_raw if str(item).strip()
            ]
        else:
            message_ids = []

        prompt = template.format(
            historical_events=_escape_braces(historical_lines),
            canonical_text=_escape_braces(canonical),
            observations=_escape_braces(observations_text),
            new_info=_escape_braces(observations_text),
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            target_perspective=perspective,
            target_display_name=_escape_braces(preferred_name or entity_id),
            request_type=_escape_braces(str(job.get("request_type", ""))),
            user_id=_escape_braces(str(job.get("user_id", ""))),
            group_id=_escape_braces(str(job.get("group_id", ""))),
            sender_id=_escape_braces(str(job.get("sender_id", ""))),
            sender_name=_escape_braces(str(job.get("sender_name", ""))),
            group_name=_escape_braces(str(job.get("group_name", ""))),
            now_local=_escape_braces(now_local),
            now_utc=_escape_braces(now_utc),
            profile_updated_at=_escape_braces(profile_updated_at),
            current_profile=profile_snapshot,
            timestamp_local=_escape_braces(str(job.get("timestamp_local", ""))),
            timezone=_escape_braces(timezone_label),
            event_id=_escape_braces(event_id),
            request_id=_escape_braces(str(job.get("request_id", ""))),
            end_seq=_escape_braces(str(job.get("end_seq", 0))),
            message_ids=_escape_braces(", ".join(message_ids) if message_ids else "[]"),
            memo=_escape_braces(str(job.get("memo", job.get("action_summary", "")))),
            action_summary=_escape_braces(
                str(job.get("memo", job.get("action_summary", "")))
            ),
            source_message=_escape_braces(str(job.get("source_message", ""))),
            recent_messages=_escape_braces(
                "\n".join(
                    f"- {str(item).strip()}"
                    for item in (job.get("recent_messages", []) or [])
                    if str(item).strip()
                )
                or "（无）"
            ),
        )

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tools = [_READ_PROFILE_TOOL, _PROFILE_TOOL]
        result = False
        max_turns = 100
        transport_state: dict[str, Any] | None = None

        for turn in range(max_turns):
            response = await self._ai_client.submit_background_llm_call(
                model_config=self._model_config or self._ai_client.agent_config,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                call_type="historian_profile_merge",
                transport_state=transport_state,
            )

            next_transport_state = (
                response.get("_transport_state") if isinstance(response, dict) else None
            )
            transport_state = (
                next_transport_state if isinstance(next_transport_state, dict) else None
            )

            choices = response.get("choices") or []
            if not choices:
                logger.warning("[史官] 任务 %s turn=%s 响应无 choices", event_id, turn)
                break
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            if not isinstance(message, dict):
                break

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                logger.info(
                    "[史官] 任务 %s turn=%s 无 tool_calls，结束", event_id, turn
                )
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": tool_calls,
            }
            if message.get("content"):
                assistant_msg["content"] = message["content"]
            output_items = message.get(RESPONSES_OUTPUT_ITEMS_KEY)
            if isinstance(output_items, list):
                assistant_msg[RESPONSES_OUTPUT_ITEMS_KEY] = output_items
            messages.append(assistant_msg)

            tool_results: list[dict[str, Any]] = []
            done = False

            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") or {}
                tc_name = str(func.get("name", "")).strip()
                tc_id = str(tc.get("id", "")).strip()
                try:
                    tc_args: dict[str, Any] = json.loads(
                        str(func.get("arguments", "{}"))
                    )
                except json.JSONDecodeError:
                    tc_args = {}

                if tc_name == "read_profile":
                    rp_et = str(tc_args.get("entity_type", "")).strip()
                    rp_eid = str(tc_args.get("entity_id", "")).strip()
                    if (
                        rp_et not in {"user", "group"}
                        or not rp_eid
                        or not rp_eid.isalnum()
                    ):
                        tc_content = "错误：entity_type 或 entity_id 无效"
                    elif (rp_et, rp_eid) == (entity_type, entity_id):
                        tc_content = profile_snapshot
                    else:
                        profile_text = await self._profile_storage.read_profile(
                            rp_et, rp_eid
                        )
                        tc_content = (
                            profile_text if profile_text is not None else "（暂无侧写）"
                        )
                    logger.info(
                        "[史官] 任务 %s read_profile: %s:%s len=%s",
                        event_id,
                        rp_et,
                        rp_eid,
                        len(tc_content),
                    )
                    tool_results.append(
                        {"role": "tool", "tool_call_id": tc_id, "content": tc_content}
                    )

                elif tc_name == "update_profile":
                    up_et = str(tc_args.get("entity_type", entity_type)).strip()
                    up_eid = str(tc_args.get("entity_id", entity_id)).strip()
                    if (
                        up_et not in {"user", "group"}
                        or not up_eid
                        or not up_eid.isalnum()
                    ):
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": "错误：entity_type 或 entity_id 无效",
                            }
                        )
                        continue
                    if (up_et, up_eid) != (entity_type, entity_id):
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": "错误：只能更新本次目标实体",
                            }
                        )
                        continue
                    raw_skip = tc_args.get("skip", False)
                    skip = (
                        raw_skip.lower() not in ("false", "0", "no", "")
                        if isinstance(raw_skip, str)
                        else bool(raw_skip)
                    )
                    if skip:
                        skip_reason = str(tc_args.get("skip_reason", "")).strip()
                        logger.info(
                            "[史官] 任务 %s 侧写更新跳过: target=%s:%s perspective=%s reason=%s",
                            event_id,
                            up_et,
                            up_eid,
                            perspective,
                            skip_reason or "unspecified",
                        )
                        await run_cancellation_safe(
                            self._commit_profile_target(job, event_id, target, progress)
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"已跳过: {skip_reason}",
                            }
                        )
                        done = True
                        break

                    summary = str(tc_args.get("summary", "")).strip()
                    evaluation = str(tc_args.get("evaluation", "")).strip()
                    roast = str(tc_args.get("roast", "")).strip()
                    section_error = (
                        _profile_section_error(
                            summary,
                            empty_reason="empty_summary",
                            empty_content="错误：summary 为空",
                            delimiter_reason="summary_delimiter",
                            delimiter_content="错误：正文不能包含单独成行的 ---",
                        )
                        or _profile_section_error(
                            evaluation,
                            empty_reason="empty_evaluation",
                            empty_content="错误：evaluation 为空",
                            delimiter_reason="evaluation_delimiter",
                            delimiter_content="错误：评价段不能包含单独成行的 ---",
                        )
                        or _profile_section_error(
                            roast,
                            empty_reason="empty_roast",
                            empty_content="错误：roast 为空",
                            delimiter_reason="roast_delimiter",
                            delimiter_content="错误：锐评不能包含单独成行的 ---",
                        )
                    )
                    if section_error is not None:
                        skip_reason, error_content = section_error
                        logger.info(
                            "[史官] 任务 %s 侧写更新跳过: target=%s:%s reason=%s",
                            event_id,
                            up_et,
                            up_eid,
                            skip_reason,
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": error_content,
                            }
                        )
                        continue
                    raw_tags = tc_args.get("tags", [])
                    up_tags: list[str] = []
                    if isinstance(raw_tags, list):
                        up_tags = [str(t).strip() for t in raw_tags if str(t).strip()]

                    llm_name = str(tc_args.get("name", "")).strip()
                    is_target = up_et == entity_type and up_eid == entity_id
                    name_hint = preferred_name if is_target else ""
                    if not llm_name and not name_hint:
                        existing = await self._profile_storage.read_profile(
                            up_et, up_eid
                        )
                        fallback_name = _extract_frontmatter_name(existing or "")
                    else:
                        fallback_name = ""
                    effective_name = (
                        name_hint
                        or llm_name
                        or fallback_name
                        or (f"GID:{up_eid}" if up_et == "group" else f"UID:{up_eid}")
                    )

                    await run_cancellation_safe(
                        self._commit_profile_target(
                            job,
                            event_id,
                            target,
                            progress,
                            self._write_profile(
                                entity_type=up_et,
                                entity_id=up_eid,
                                effective_name=effective_name,
                                tags=up_tags,
                                summary=summary,
                                evaluation=evaluation,
                                roast=roast,
                                event_id=event_id,
                                perspective=perspective,
                                now_timezone=now_local_dt.tzinfo,
                            ),
                        )
                    )
                    tool_results.append(
                        {"role": "tool", "tool_call_id": tc_id, "content": "侧写已更新"}
                    )
                    result = True
                    done = True
                    break

                else:
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"未知工具: {tc_name}",
                        }
                    )

            messages.extend(tool_results)
            if done:
                return result

        raise RuntimeError(
            f"侧写合并未产生有效更新或明确跳过: {event_id} {entity_type}:{entity_id}"
        )
