"""知识库管理器"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Undefined.knowledge.chunker import split_lines
from Undefined.knowledge.store import KnowledgeStore

if TYPE_CHECKING:
    from Undefined.knowledge.embedder import Embedder

logger = logging.getLogger(__name__)

_MANIFEST_FILE = ".manifest.json"


class KnowledgeManager:
    def __init__(
        self,
        base_dir: str | Path,
        embedder: Embedder,
        default_top_k: int = 5,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._embedder = embedder
        self._default_top_k = default_top_k
        self._stores: dict[str, KnowledgeStore] = {}
        self._scan_task: asyncio.Task[None] | None = None

    def _get_store(self, name: str) -> KnowledgeStore:
        if name not in self._stores:
            chroma_dir = self._base_dir / name / "chroma"
            chroma_dir.mkdir(parents=True, exist_ok=True)
            self._stores[name] = KnowledgeStore(name, chroma_dir)
        return self._stores[name]

    def list_knowledge_bases(self) -> list[str]:
        if not self._base_dir.exists():
            return []
        return [
            d.name
            for d in sorted(self._base_dir.iterdir())
            if d.is_dir() and (d / "texts").exists()
        ]

    async def _load_manifest(self, kb_name: str) -> dict[str, str]:
        path = self._base_dir / kb_name / _MANIFEST_FILE
        if not path.exists():
            return {}
        text = await asyncio.to_thread(path.read_text, "utf-8")
        return json.loads(text)  # type: ignore[no-any-return]

    async def _save_manifest(self, kb_name: str, manifest: dict[str, str]) -> None:
        path = self._base_dir / kb_name / _MANIFEST_FILE
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        await asyncio.to_thread(path.write_text, content, "utf-8")

    async def _file_hash(self, path: Path) -> str:
        data = await asyncio.to_thread(path.read_bytes)
        return hashlib.sha256(data).hexdigest()[:16]

    async def embed_knowledge_base(self, kb_name: str) -> int:
        """扫描并嵌入一个知识库的新增/变更文件，返回新增行数。"""
        texts_dir = self._base_dir / kb_name / "texts"
        if not texts_dir.exists():
            return 0

        manifest = await self._load_manifest(kb_name)
        store = self._get_store(kb_name)
        total = 0

        for txt_file in sorted(texts_dir.glob("*.txt")):
            fhash = await self._file_hash(txt_file)
            if manifest.get(txt_file.name) == fhash:
                continue
            content = await asyncio.to_thread(txt_file.read_text, "utf-8")
            lines = split_lines(content)
            if not lines:
                manifest[txt_file.name] = fhash
                continue
            embeddings = await self._embedder.embed(lines)
            added = await store.add_chunks(
                lines,
                embeddings,
                metadata_base={"source": txt_file.name, "kb": kb_name},
            )
            manifest[txt_file.name] = fhash
            total += added
            logger.info(
                "[知识库] kb=%s file=%s lines=%s", kb_name, txt_file.name, added
            )

        await self._save_manifest(kb_name, manifest)
        return total

    async def scan_and_embed_all(self) -> int:
        total = 0
        for kb_name in self.list_knowledge_bases():
            try:
                total += await self.embed_knowledge_base(kb_name)
            except Exception as exc:
                logger.error("[知识库] 嵌入失败: kb=%s error=%s", kb_name, exc)
        return total

    def text_search(
        self,
        kb_name: str,
        keyword: str,
        max_lines: int = 20,
        max_chars: int = 2000,
    ) -> list[dict[str, Any]]:
        """在指定知识库的原始文本中关键词搜索。"""
        texts_dir = self._base_dir / kb_name / "texts"
        if not texts_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        total_chars = 0
        kw_lower = keyword.lower()

        for txt_file in sorted(texts_dir.glob("*.txt")):
            try:
                content = txt_file.read_text("utf-8")
            except OSError:
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                if kw_lower in line.lower():
                    results.append(
                        {"source": txt_file.name, "line": lineno, "content": line}
                    )
                    total_chars += len(line)
                    if len(results) >= max_lines or total_chars >= max_chars:
                        return results
        return results

    async def semantic_search(
        self,
        kb_name: str,
        query: str,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """在指定知识库中语义搜索。"""
        k = top_k or self._default_top_k
        instruction = getattr(self._embedder._config, "query_instruction", "")
        query_input = f"{instruction}{query}" if instruction else query
        query_emb = (await self._embedder.embed([query_input]))[0]
        return await self._get_store(kb_name).query(query_emb, k)

    def start_auto_scan(self, interval: float) -> None:
        if self._scan_task is not None:
            return
        self._scan_task = asyncio.create_task(self._auto_scan_loop(interval))

    async def _auto_scan_loop(self, interval: float) -> None:
        while True:
            try:
                added = await self.scan_and_embed_all()
                if added:
                    logger.info("[知识库] 自动扫描: 新增 %s 行", added)
            except Exception as exc:
                logger.error("[知识库] 自动扫描异常: %s", exc)
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        if self._scan_task:
            self._scan_task.cancel()
            self._scan_task = None
