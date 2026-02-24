#!/usr/bin/env python3
"""认知记忆向量库重嵌入脚本。

当更换嵌入模型（维度变化或模型升级）时，使用此脚本对 ChromaDB 中的
cognitive_events 和 cognitive_profiles 两个 collection 进行全量重嵌入。

原理：ChromaDB 存储了完整的原文本（documents），本脚本读取所有记录，
用新模型重新计算向量，然后通过 upsert 覆写回去。metadata 保持不变。

用法：
    # 先在 config.toml 中更新 [models.embedding] 为新模型配置
    uv run python scripts/reembed_cognitive.py

    # 仅重嵌入事件（跳过侧写）
    uv run python scripts/reembed_cognitive.py --events-only

    # 仅重嵌入侧写（跳过事件）
    uv run python scripts/reembed_cognitive.py --profiles-only

    # 自定义批大小（默认 32）
    uv run python scripts/reembed_cognitive.py --batch-size 16

    # 模拟运行（不实际写入）
    uv run python scripts/reembed_cognitive.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

import chromadb
import httpx

# 将项目 src 加入 sys.path，使脚本可以直接 uv run 执行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from Undefined.ai.llm import ModelRequester  # noqa: E402
from Undefined.config.loader import Config  # noqa: E402
from Undefined.config.models import EmbeddingModelConfig  # noqa: E402
from Undefined.knowledge.embedder import Embedder  # noqa: E402
from Undefined.token_usage_storage import TokenUsageStorage  # noqa: E402

logger = logging.getLogger("reembed_cognitive")

# ChromaDB get() 单次最大拉取量
_CHROMA_GET_LIMIT = 5000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="认知记忆向量库重嵌入：更换嵌入模型后重新计算所有向量",
    )
    parser.add_argument(
        "--events-only",
        action="store_true",
        help="仅重嵌入 cognitive_events（跳过 cognitive_profiles）",
    )
    parser.add_argument(
        "--profiles-only",
        action="store_true",
        help="仅重嵌入 cognitive_profiles（跳过 cognitive_events）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="每批嵌入的文档数（默认 32，降低可减小 API 压力）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行：计算向量但不写入 ChromaDB",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="ChromaDB 路径（默认读取 config.toml 中的 cognitive.vector_store_path）",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="显示详细日志",
    )
    return parser.parse_args()


def _get_all_records(
    collection: Any,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """分页读取 collection 中的所有记录，返回 (ids, documents, metadatas)。"""
    all_ids: list[str] = []
    all_docs: list[str] = []
    all_metas: list[dict[str, Any]] = []

    total = collection.count()
    if total == 0:
        return all_ids, all_docs, all_metas

    offset = 0
    while offset < total:
        batch = collection.get(
            include=["documents", "metadatas"],
            limit=_CHROMA_GET_LIMIT,
            offset=offset,
        )
        batch_ids: list[str] = batch.get("ids", [])
        batch_docs: list[str] = batch.get("documents", [])
        batch_metas: list[dict[str, Any]] = batch.get("metadatas", [])

        if not batch_ids:
            break

        all_ids.extend(batch_ids)
        all_docs.extend(batch_docs)
        all_metas.extend(batch_metas)
        offset += len(batch_ids)

    return all_ids, all_docs, all_metas


async def _reembed_collection(
    collection: Any,
    collection_name: str,
    embedder: Embedder,
    batch_size: int,
    dry_run: bool,
) -> int:
    """对单个 collection 执行全量重嵌入，返回处理的记录数。"""
    logger.info("正在读取 %s ...", collection_name)
    ids, docs, metas = _get_all_records(collection)
    total = len(ids)

    if total == 0:
        logger.info("%s 为空，跳过。", collection_name)
        return 0

    logger.info(
        "%s 共 %d 条记录，开始重嵌入 (batch_size=%d)...",
        collection_name,
        total,
        batch_size,
    )

    processed = 0
    start_time = time.perf_counter()

    for i in range(0, total, batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_docs = docs[i : i + batch_size]
        batch_metas = metas[i : i + batch_size]

        # 计算新向量
        new_embeddings = await embedder.embed(batch_docs)

        if not dry_run:
            # upsert 覆写：ID 不变，document 和 metadata 不变，仅更新 embedding
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                embeddings=new_embeddings,
                metadatas=batch_metas,
            )

        processed += len(batch_ids)
        elapsed = time.perf_counter() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        logger.info(
            "  [%s] %d/%d (%.1f%%) — %.1f 条/秒%s",
            collection_name,
            processed,
            total,
            processed / total * 100,
            rate,
            " (dry-run)" if dry_run else "",
        )

    elapsed_total = time.perf_counter() - start_time
    logger.info(
        "%s 完成：%d 条记录，耗时 %.1f 秒%s",
        collection_name,
        processed,
        elapsed_total,
        " (dry-run，未实际写入)" if dry_run else "",
    )
    return processed


def _build_embedder(config: Config) -> Embedder:
    """根据 config.toml 构建 Embedder 实例。"""
    embedding_config: EmbeddingModelConfig = config.embedding_model
    if not embedding_config.api_url or not embedding_config.model_name:
        logger.error(
            "config.toml 中 [models.embedding] 未配置 api_url 或 model_name，无法继续。"
        )
        sys.exit(1)

    http_client = httpx.AsyncClient(timeout=120.0)
    token_storage = TokenUsageStorage()
    model_requester = ModelRequester(http_client, token_storage)
    embedder = Embedder(model_requester, embedding_config, batch_size=64)
    embedder.start()
    return embedder


async def _main(args: argparse.Namespace) -> None:
    config = Config.load(strict=False)

    db_path = args.db_path or config.cognitive.vector_store_path
    logger.info("ChromaDB 路径: %s", db_path)
    logger.info(
        "嵌入模型: %s (dimensions=%s)",
        config.embedding_model.model_name,
        config.embedding_model.dimensions or "auto",
    )

    if not Path(db_path).exists():
        logger.error("ChromaDB 目录不存在: %s", db_path)
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(db_path))
    embedder = _build_embedder(config)

    total_processed = 0

    try:
        if not args.profiles_only:
            events_col = client.get_or_create_collection(
                "cognitive_events", metadata={"hnsw:space": "cosine"}
            )
            total_processed += await _reembed_collection(
                events_col, "cognitive_events", embedder, args.batch_size, args.dry_run
            )

        if not args.events_only:
            profiles_col = client.get_or_create_collection(
                "cognitive_profiles", metadata={"hnsw:space": "cosine"}
            )
            total_processed += await _reembed_collection(
                profiles_col,
                "cognitive_profiles",
                embedder,
                args.batch_size,
                args.dry_run,
            )
    finally:
        await embedder.stop()

    logger.info("全部完成，共处理 %d 条记录。", total_processed)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.events_only and args.profiles_only:
        logger.error("--events-only 和 --profiles-only 不能同时指定。")
        sys.exit(1)

    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
