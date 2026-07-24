"""Task-local references for canonical lxmusic2api Track objects."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from secrets import token_urlsafe
from typing import Final


MUSIC_TRACK_STORE_CONTEXT_KEY: Final = "music_track_reference_store"
DEFAULT_MAX_TRACK_REFERENCES: Final = 4096


class MusicTrackReferenceError(ValueError):
    """Raised when a task-local music Track reference cannot be resolved."""


class MusicTrackReferenceStore:
    """Keep canonical Track objects behind compact references for one AI task."""

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_TRACK_REFERENCES,
        reference_namespace: str | None = None,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        namespace = str(reference_namespace or "").strip() or token_urlsafe(6)
        if len(namespace) > 32 or not all(
            character.isalnum() or character in {"-", "_"} for character in namespace
        ):
            raise ValueError("reference_namespace 格式无效")
        self._max_entries = max_entries
        self._reference_prefix = f"mtrk_{namespace}_"
        self._next_reference = 1
        self._tracks: OrderedDict[str, dict[str, object]] = OrderedDict()
        self._references_by_identity: dict[tuple[str, str], str] = {}

    @staticmethod
    def _identity(track: Mapping[str, object]) -> tuple[str, str]:
        source = str(track.get("source", "") or "").strip()
        track_id = str(track.get("id", "") or "").strip()
        if not source or not track_id:
            raise MusicTrackReferenceError("Track 缺少 source 或 id，无法创建引用")
        return source, track_id

    def register(self, track: Mapping[str, object]) -> str:
        """Register a Track and return a stable reference within this task."""
        identity = self._identity(track)
        stored_track = deepcopy(dict(track))
        existing_reference = self._references_by_identity.get(identity)
        if existing_reference is not None and existing_reference in self._tracks:
            self._tracks[existing_reference] = stored_track
            self._tracks.move_to_end(existing_reference)
            return existing_reference

        reference = f"{self._reference_prefix}{self._next_reference}"
        self._next_reference += 1
        self._tracks[reference] = stored_track
        self._references_by_identity[identity] = reference
        self._prune()
        return reference

    def resolve(self, reference: str) -> dict[str, object]:
        """Resolve a reference and return an isolated copy of its Track."""
        normalized_reference = str(reference or "").strip()
        if not normalized_reference:
            raise MusicTrackReferenceError("track_ref 不能为空")
        track = self._tracks.get(normalized_reference)
        if track is None:
            raise MusicTrackReferenceError(
                "track_ref 无效、已淘汰或不属于当前任务，请重新搜索歌曲后使用新的引用"
            )
        self._tracks.move_to_end(normalized_reference)
        return deepcopy(track)

    def _prune(self) -> None:
        while len(self._tracks) > self._max_entries:
            reference, track = self._tracks.popitem(last=False)
            identity = self._identity(track)
            if self._references_by_identity.get(identity) == reference:
                del self._references_by_identity[identity]
