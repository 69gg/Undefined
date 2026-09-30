"""史官持久化阶段进度及按实体就绪选择；不创建等待任务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from Undefined.cognitive.job_queue import QueuedJob

EntityKey = tuple[str, str]
PROGRESS_FIELD = "_historian_progress"


def observations(job: dict[str, Any]) -> list[str]:
    raw = job.get("observations", job.get("new_info", []))
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def resolve_profile_targets(job: dict[str, Any]) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen: set[EntityKey] = set()
    raw_targets = job.get("profile_targets")
    if isinstance(raw_targets, list):
        for item in raw_targets:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type", "")).strip()
            entity_id = str(item.get("entity_id") or "").strip()
            key = (entity_type, entity_id)
            if entity_type not in {"user", "group"} or not entity_id or key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "perspective": str(item.get("perspective", "")).strip(),
                    "preferred_name": str(item.get("preferred_name", "")).strip(),
                }
            )
    if targets:
        return targets
    entity_type = "group" if str(job.get("group_id") or "").strip() else "user"
    entity_id = str(
        job.get("group_id") or job.get("user_id") or job.get("sender_id") or ""
    ).strip()
    if entity_id:
        targets.append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "perspective": "legacy",
                "preferred_name": "",
            }
        )
    return targets


def target_key(target: dict[str, str]) -> EntityKey:
    return target["entity_type"], target["entity_id"]


@dataclass
class HistorianProgress:
    rewrites: list[str] = field(default_factory=list)
    events_written: int = 0
    completed_targets: list[str] = field(default_factory=list)

    @classmethod
    def from_job(cls, job: dict[str, Any]) -> HistorianProgress:
        raw = job.get(PROGRESS_FIELD, {})
        if not isinstance(raw, dict):
            raise ValueError("非法的史官进度")
        rewrites = raw.get("rewrites", [])
        written = raw.get("events_written", 0)
        completed = raw.get("completed_targets", [])
        if (
            not isinstance(rewrites, list)
            or not all(isinstance(item, str) for item in rewrites)
            or not isinstance(written, int)
            or not 0 <= written <= len(rewrites)
            or not isinstance(completed, list)
            or not all(isinstance(item, str) for item in completed)
        ):
            raise ValueError("非法的史官阶段进度字段")
        return cls(list(rewrites), written, list(completed))

    def store(self, job: dict[str, Any]) -> None:
        job[PROGRESS_FIELD] = {
            "rewrites": list(self.rewrites),
            "events_written": self.events_written,
            "completed_targets": list(self.completed_targets),
        }

    def finish_target(self, target: dict[str, str]) -> None:
        self.completed_targets.append(":".join(target_key(target)))

    def pending_targets(self, job: dict[str, Any]) -> list[dict[str, str]]:
        if not job.get(
            "has_observations", job.get("has_new_info", False)
        ) or not observations(job):
            return []
        return [
            target
            for target in resolve_profile_targets(job)
            if ":".join(target_key(target)) not in self.completed_targets
        ]


@dataclass(frozen=True)
class ReadyPhase:
    entry: QueuedJob
    target: dict[str, str] | None = None


def select_ready_phase(
    entries: list[QueuedJob], active: dict[str, EntityKey | None]
) -> ReadyPhase | None:
    """entries 已按入队顺序排序；未就绪/遗留 processing 仍占实体队首。"""
    heads: dict[EntityKey, str] = {}
    active_entities = {key for key in active.values() if key is not None}
    candidates: list[tuple[QueuedJob, HistorianProgress, list[dict[str, str]]]] = []
    for entry in entries:
        progress = HistorianProgress.from_job(entry.data)
        targets = progress.pending_targets(entry.data)
        for target in targets:
            heads.setdefault(target_key(target), entry.job_id)
        candidates.append((entry, progress, targets))
    for entry, progress, targets in candidates:
        if entry.state != "pending" or entry.job_id in active:
            continue
        if progress.events_written < len(observations(entry.data)) or not targets:
            return ReadyPhase(entry)
        for target in targets:
            key = target_key(target)
            if heads[key] == entry.job_id and key not in active_entities:
                return ReadyPhase(entry, target)
    return None
