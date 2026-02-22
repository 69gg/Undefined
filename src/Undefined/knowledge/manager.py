"""知识库管理器"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from Undefined.knowledge.chunker import chunk_lines
from Undefined.knowledge.store import KnowledgeStore

if TYPE_CHECKING:
    from Undefined.knowledge.embedder import Embedder
    from Undefined.knowledge.reranker import Reranker

logger = logging.getLogger(__name__)

_MANIFEST_FILE = ".manifest.json"
_INTRO_FILE = "intro.md"
_IGNORED_DIRS = {"chroma", ".git", "__pycache__"}
_SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".html",
    ".htm",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".log",
    ".ini",
    ".cfg",
    ".conf",
}


class KnowledgeManager:
    def __init__(
        self,
        base_dir: str | Path,
        embedder: Embedder,
        reranker: Reranker | None = None,
        default_top_k: int = 5,
        chunk_size: int = 10,
        chunk_overlap: int = 2,
        rerank_enabled: bool = False,
        rerank_top_k: int = 3,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._embedder = embedder
        self._reranker = reranker
        self._default_top_k = default_top_k
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._rerank_enabled = rerank_enabled
        self._rerank_top_k = rerank_top_k
        self._stores: dict[str, KnowledgeStore] = {}
        self._scan_task: asyncio.Task[None] | None = None

    def _get_store(self, name: str) -> KnowledgeStore:
        if name not in self._stores:
            chroma_dir = self._base_dir / name / "chroma"
            chroma_dir.mkdir(parents=True, exist_ok=True)
            self._stores[name] = KnowledgeStore(name, chroma_dir)
        return self._stores[name]

    def _get_existing_store(self, name: str) -> KnowledgeStore | None:
        cached = self._stores.get(name)
        if cached is not None:
            return cached
        chroma_dir = self._base_dir / name / "chroma"
        if not chroma_dir.exists() or not chroma_dir.is_dir():
            return None
        store = KnowledgeStore(name, chroma_dir)
        self._stores[name] = store
        return store

    def list_knowledge_bases(self) -> list[str]:
        if not self._base_dir.exists():
            return []
        return [
            d.name
            for d in sorted(self._base_dir.iterdir())
            if d.is_dir() and (d / "texts").exists()
        ]

    def _is_supported_text_file(self, path: Path) -> bool:
        if path.name in {_MANIFEST_FILE, _INTRO_FILE}:
            return False
        return path.suffix.lower() in _SUPPORTED_TEXT_EXTENSIONS

    def _iter_indexable_text_files(self, kb_dir: Path) -> list[Path]:
        texts_dir = kb_dir / "texts"
        if not texts_dir.exists() or not texts_dir.is_dir():
            return []

        files: list[Path] = []
        for root, dirnames, filenames in os.walk(texts_dir):
            dirnames[:] = [
                d
                for d in dirnames
                if d.lower() not in _IGNORED_DIRS and not d.startswith(".")
            ]
            root_path = Path(root)
            for name in filenames:
                file_path = root_path / name
                if not self._is_supported_text_file(file_path):
                    continue
                files.append(file_path)

        files.sort(key=lambda p: p.relative_to(kb_dir).as_posix())
        return files

    def read_knowledge_base_intro(self, kb_name: str, max_chars: int = 300) -> str:
        intro_path = self._base_dir / kb_name / _INTRO_FILE
        if not intro_path.exists():
            return ""
        try:
            intro = intro_path.read_text("utf-8").strip()
        except OSError:
            return ""
        if max_chars <= 0 or len(intro) <= max_chars:
            return intro
        return f"{intro[: max_chars - 1].rstrip()}…"

    def list_knowledge_base_infos(
        self,
        intro_max_chars: int = 300,
        only_ready: bool = False,
    ) -> list[dict[str, Any]]:
        infos: list[dict[str, Any]] = []
        for kb_name in self.list_knowledge_bases():
            intro = self.read_knowledge_base_intro(kb_name, max_chars=intro_max_chars)
            has_intro = bool(intro)
            if only_ready and not has_intro:
                continue
            infos.append(
                {
                    "name": kb_name,
                    "intro": intro,
                    "has_intro": has_intro,
                }
            )
        return infos

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
        kb_dir = self._base_dir / kb_name
        if not kb_dir.exists():
            return 0

        manifest = await self._load_manifest(kb_name)
        text_files = self._iter_indexable_text_files(kb_dir)
        current_sources = {path.relative_to(kb_dir).as_posix() for path in text_files}
        removed_sources = sorted(set(manifest) - current_sources)

        store: KnowledgeStore | None = None
        total = 0
        manifest_changed = False

        if removed_sources:
            store = self._get_store(kb_name)
            for source in removed_sources:
                await store.delete_by_source(source)
                manifest.pop(source, None)
                manifest_changed = True
                logger.info("[知识库] kb=%s removed source=%s", kb_name, source)

        for text_file in text_files:
            relative_source = text_file.relative_to(kb_dir).as_posix()
            fhash = await self._file_hash(text_file)
            if manifest.get(relative_source) == fhash:
                continue
            if store is None:
                store = self._get_store(kb_name)
            await store.delete_by_source(relative_source)
            try:
                content = await asyncio.to_thread(text_file.read_text, "utf-8")
            except (OSError, UnicodeDecodeError):
                if manifest.pop(relative_source, None) is not None:
                    manifest_changed = True
                continue
            lines = chunk_lines(content, self._chunk_size, self._chunk_overlap)
            if not lines:
                manifest[relative_source] = fhash
                manifest_changed = True
                continue
            doc_instr = getattr(self._embedder._config, "document_instruction", "")
            embed_lines = [f"{doc_instr}{ln}" for ln in lines] if doc_instr else lines
            embeddings = await self._embedder.embed(embed_lines)
            added = await store.add_chunks(
                lines,
                embeddings,
                metadata_base={"source": relative_source, "kb": kb_name},
            )
            manifest[relative_source] = fhash
            manifest_changed = True
            total += added
            logger.info(
                "[知识库] kb=%s file=%s lines=%s", kb_name, relative_source, added
            )

        if manifest_changed:
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
        case_sensitive: bool = False,
        source_keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """在指定知识库的原始文本中关键词搜索。"""
        kb_dir = self._base_dir / kb_name
        if not kb_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        total_chars = 0
        keyword_cmp = keyword if case_sensitive else keyword.lower()
        source_kw = (source_keyword or "").strip()
        source_kw_cmp = source_kw if case_sensitive else source_kw.lower()

        for text_file in self._iter_indexable_text_files(kb_dir):
            relative_source = text_file.relative_to(kb_dir).as_posix()
            if source_kw_cmp:
                source_cmp = (
                    relative_source if case_sensitive else relative_source.lower()
                )
                if source_kw_cmp not in source_cmp:
                    continue
            try:
                content = text_file.read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(content.splitlines(), 1):
                line_cmp = line if case_sensitive else line.lower()
                if keyword_cmp in line_cmp:
                    results.append(
                        {"source": relative_source, "line": lineno, "content": line}
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
        enable_rerank: bool | None = None,
        rerank_top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """在指定知识库中语义搜索。"""
        kb_dir = self._base_dir / kb_name
        if not kb_dir.exists() or not (kb_dir / "texts").exists():
            return []
        store = self._get_existing_store(kb_name)
        if store is None:
            return []

        k = top_k or self._default_top_k
        if k <= 0:
            k = self._default_top_k
        instruction = getattr(self._embedder._config, "query_instruction", "")
        query_input = f"{instruction}{query}" if instruction else query
        query_emb = (await self._embedder.embed([query_input]))[0]
        results = await store.query(query_emb, k)
        if not results:
            return []

        should_rerank, final_rerank_top_k = self._resolve_rerank_plan(
            semantic_top_k=k,
            enable_rerank=enable_rerank,
            rerank_top_k=rerank_top_k,
        )
        if not should_rerank:
            return results
        return await self._apply_rerank(
            query=query,
            results=results,
            rerank_top_k=final_rerank_top_k,
        )

    def _resolve_rerank_plan(
        self,
        *,
        semantic_top_k: int,
        enable_rerank: bool | None,
        rerank_top_k: int | None,
    ) -> tuple[bool, int]:
        if self._reranker is None:
            return False, 0

        enabled = self._rerank_enabled if enable_rerank is None else bool(enable_rerank)
        if not enabled:
            return False, 0
        if semantic_top_k <= 1:
            return False, 0

        candidate_top_k = self._rerank_top_k if rerank_top_k is None else rerank_top_k
        if candidate_top_k <= 0:
            return False, 0

        if candidate_top_k >= semantic_top_k:
            candidate_top_k = semantic_top_k - 1
        if candidate_top_k <= 0:
            return False, 0
        return True, candidate_top_k

    async def _apply_rerank(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        rerank_top_k: int,
    ) -> list[dict[str, Any]]:
        if self._reranker is None or not results:
            return results

        docs = [str(item.get("content", "")) for item in results]
        try:
            reranked = await self._reranker.rerank(
                query=query,
                documents=docs,
                top_n=min(rerank_top_k, len(docs)),
            )
        except Exception as exc:
            logger.warning("[知识库] 重排失败，已回退语义结果: error=%s", exc)
            return results

        reordered: list[dict[str, Any]] = []
        used_indices: set[int] = set()
        for item in reranked:
            idx_raw = item.get("index")
            if isinstance(idx_raw, int):
                idx = idx_raw
            elif isinstance(idx_raw, str):
                try:
                    idx = int(idx_raw)
                except ValueError:
                    continue
            elif isinstance(idx_raw, float):
                idx = int(idx_raw)
            else:
                continue
            if idx < 0 or idx >= len(results) or idx in used_indices:
                continue
            enriched = dict(results[idx])
            try:
                enriched["rerank_score"] = float(item.get("relevance_score", 0.0))
            except (TypeError, ValueError):
                enriched["rerank_score"] = 0.0
            reordered.append(enriched)
            used_indices.add(idx)
            if len(reordered) >= rerank_top_k:
                break

        if reordered:
            return reordered
        return results[:rerank_top_k]

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
            with suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None
        await self._embedder.stop()
        if self._reranker:
            await self._reranker.stop()
