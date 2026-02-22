"""侧写文件管理，Markdown + YAML Frontmatter。"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProfileStorage:
    def __init__(self, base_path: str | Path, revision_keep: int = 5) -> None:
        self._base = Path(base_path)
        self._revision_keep = revision_keep
        self._locks: dict[str, asyncio.Lock] = {}
        logger.info(
            "[认知侧写] 初始化完成: base=%s revision_keep=%s",
            str(self._base),
            self._revision_keep,
        )

    def _get_lock(self, entity_type: str, entity_id: str) -> asyncio.Lock:
        key = f"{entity_type}:{entity_id}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _profile_path(self, entity_type: str, entity_id: str) -> Path:
        return self._base / f"{entity_type}s" / f"{entity_id}.md"

    def _history_dir(self, entity_type: str, entity_id: str) -> Path:
        return self._base / "history" / entity_type / entity_id

    async def read_profile(self, entity_type: str, entity_id: str) -> str | None:
        p = self._profile_path(entity_type, entity_id)
        logger.info(
            "[认知侧写] 读取侧写: entity_type=%s entity_id=%s", entity_type, entity_id
        )

        def _read() -> str | None:
            if not p.exists():
                return None
            return p.read_text(encoding="utf-8")

        result = await asyncio.to_thread(_read)
        logger.info(
            "[认知侧写] 读取完成: entity_type=%s entity_id=%s found=%s len=%s",
            entity_type,
            entity_id,
            bool(result),
            len(result or ""),
        )
        return result

    async def write_profile(
        self, entity_type: str, entity_id: str, content: str
    ) -> None:
        logger.info(
            "[认知侧写] 写入侧写: entity_type=%s entity_id=%s content_len=%s",
            entity_type,
            entity_id,
            len(content or ""),
        )
        async with self._get_lock(entity_type, entity_id):
            p = self._profile_path(entity_type, entity_id)
            hist_dir = self._history_dir(entity_type, entity_id)

            def _write() -> None:
                p.parent.mkdir(parents=True, exist_ok=True)
                hist_dir.mkdir(parents=True, exist_ok=True)

                # 备份现有版本
                if p.exists():
                    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
                    (hist_dir / f"{ts}.md").write_text(
                        p.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                    logger.info(
                        "[认知侧写] 已创建历史快照: entity_type=%s entity_id=%s snapshot=%s.md",
                        entity_type,
                        entity_id,
                        ts,
                    )

                # 原子写入
                fd, tmp = tempfile.mkstemp(
                    prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(content)
                    os.replace(tmp, p)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise

                # 清理旧快照
                snapshots = sorted(hist_dir.glob("*.md"))
                for old in snapshots[: max(0, len(snapshots) - self._revision_keep)]:
                    try:
                        old.unlink()
                    except OSError:
                        pass

            await asyncio.to_thread(_write)
        revisions = await self.list_revisions(entity_type, entity_id)
        logger.info(
            "[认知侧写] 写入完成: entity_type=%s entity_id=%s revisions=%s",
            entity_type,
            entity_id,
            len(revisions),
        )

    async def list_revisions(self, entity_type: str, entity_id: str) -> list[str]:
        hist_dir = self._history_dir(entity_type, entity_id)

        def _list() -> list[str]:
            if not hist_dir.exists():
                return []
            return sorted(f.name for f in hist_dir.glob("*.md"))

        result = await asyncio.to_thread(_list)
        logger.info(
            "[认知侧写] 列出历史版本: entity_type=%s entity_id=%s count=%s",
            entity_type,
            entity_id,
            len(result),
        )
        return result

    @staticmethod
    def _sanitize_profile(content: str, entity_type: str, entity_id: str) -> str:
        import yaml

        # 剥离 ```markdown / ``` 包裹
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            end = next(
                (i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == "```"),
                None,
            )
            if end:
                stripped = "\n".join(lines[1:end])

        # 解析 frontmatter
        if stripped.startswith("---"):
            parts = stripped[3:].split("---", 1)
            if len(parts) == 2:
                fm: Any = yaml.safe_load(parts[0])
                if not isinstance(fm, dict):
                    raise ValueError("frontmatter 格式错误")
                for field in ("entity_type", "entity_id"):
                    if field not in fm:
                        raise ValueError(f"缺少必要字段: {field}")

        return stripped
