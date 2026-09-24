#!/usr/bin/env python3
"""认知记忆向量库重嵌入脚本。

当更换嵌入模型（维度变化或模型升级）时，使用此脚本对 ChromaDB 中的
cognitive_events 和 cognitive_profiles 两个 collection 进行全量重嵌入。

原理：ChromaDB 存储了完整的原文本（documents），本脚本读取所有记录，
用新模型重新计算向量，然后通过 upsert 覆写回去。metadata 保持不变。

维度变化：ChromaDB 的 collection 在首次写入时定维，异维向量 upsert 会直接失败
（InvalidArgumentError）。脚本会先比较新旧向量维度，检测到变化时把新向量全部
写入临时 collection（原库在迁移完成前保持不动），全部写完并校验记录数后删除
原库、把临时 collection 原子换名回正式名称；中途被杀也不会丢库——下次运行会
自动清理遗留的临时库，或在正式库缺失时从临时库恢复。

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

# 维度迁移时临时 collection 的后缀
_STAGING_SUFFIX = "__rebuild_tmp"


def _staging_name(collection_name: str) -> str:
    return f"{collection_name}{_STAGING_SUFFIX}"


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


def _collection_dimension(collection: Any) -> int:
    """读取 collection 当前向量维度；空库或读取失败返回 0。"""
    try:
        sample = collection.get(limit=1, include=["embeddings"])
    except Exception as exc:  # pragma: no cover - 依赖 ChromaDB 内部行为
        logger.warning("读取现有向量维度失败，将按新维度直接写入: %s", exc)
        return 0
    embeddings = sample.get("embeddings")
    if embeddings is None or len(embeddings) == 0:
        return 0
    try:
        return len(embeddings[0])
    except TypeError:
        return 0


def _recover_stale_staging(client: Any, collection_name: str) -> None:
    """处理上次异常中断遗留的临时 collection，保证迁移可安全重跑。

    - 正式库仍存在：临时库只是写了一半的残留，直接删除；
    - 正式库缺失（中断发生在删原库之后、换名之前）：临时库持有全量数据，
      换名恢复成正式库。
    """
    staging_name = _staging_name(collection_name)
    names = {c.name for c in client.list_collections()}
    if staging_name not in names:
        return
    if collection_name in names:
        logger.warning(
            "发现上次运行遗留的临时 collection %s（正式库完好），已删除",
            staging_name,
        )
        client.delete_collection(staging_name)
    else:
        logger.warning(
            "发现上次运行在换名前中断：正式库 %s 缺失但临时库完好，正在恢复",
            collection_name,
        )
        client.get_collection(staging_name).modify(name=collection_name)
        logger.warning("恢复完成：%s 已从临时库换名回来", collection_name)


def _begin_dimension_migration(client: Any, collection_name: str, metadata: Any) -> Any:
    """维度变化时创建临时 collection 承接新向量；原库在迁移完成前保持不动。"""
    staging_name = _staging_name(collection_name)
    logger.warning(
        "向量维度变化，迁移写入临时 collection %s，全部写完并校验后原子换名",
        staging_name,
    )
    return client.get_or_create_collection(
        staging_name,
        metadata=metadata or {"hnsw:space": "cosine"},
    )


def _finish_dimension_migration(
    client: Any,
    collection_name: str,
    staging_collection: Any,
    *,
    expected_count: int,
    expected_dimension: int,
) -> None:
    """校验临时库记录数与向量维度后删原库、换名；失败时保留原库，可安全重跑。"""
    staged = staging_collection.count()
    if staged != expected_count:
        raise RuntimeError(
            f"临时 collection {staging_collection.name} 记录数不符: "
            f"{staged} != {expected_count}；已保留原库 {collection_name}，"
            "请排查后重跑脚本"
        )
    staged_dimension = _collection_dimension(staging_collection)
    if (
        expected_dimension
        and staged_dimension
        and staged_dimension != expected_dimension
    ):
        raise RuntimeError(
            f"临时 collection {staging_collection.name} 存在异常维度: "
            f"{staged_dimension} != {expected_dimension}；已保留原库 "
            f"{collection_name}，请排查嵌入模型输出后重跑脚本"
        )
    logger.info(
        "临时 collection 校验通过（%d 条，维度 %s），换名为 %s",
        staged,
        staged_dimension or expected_dimension,
        collection_name,
    )
    if not callable(getattr(staging_collection, "modify", None)):
        raise RuntimeError(
            "当前 ChromaDB 版本不支持 collection 换名（Collection.modify），"
            "无法安全完成维度迁移；已保留原库，请升级 chromadb 后重跑脚本"
        )
    client.delete_collection(collection_name)
    staging_collection.modify(name=collection_name)


async def _reembed_collection(
    collection: Any,
    collection_name: str,
    embedder: Embedder,
    batch_size: int,
    dry_run: bool,
    client: Any,
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

    current_dimension = _collection_dimension(collection)
    if current_dimension:
        logger.info("%s 现有向量维度: %s", collection_name, current_dimension)

    processed = 0
    dimension_checked = False
    write_target = collection
    staging_collection: Any = None
    new_dimension = 0  # 首批实测维度，后续批次逐一比对
    migration_dimension = 0
    start_time = time.perf_counter()

    for i in range(0, total, batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_docs = docs[i : i + batch_size]
        batch_metas = metas[i : i + batch_size]

        # 计算新向量
        new_embeddings = await embedder.embed(batch_docs)

        # 无论是否触发迁移，都要求所有批次维度一致：空库（current_dimension=0）
        # 或维度恰好一致时没有临时库兜底，批次漂移会直接写进 Chroma 才报错
        batch_dimension = len(new_embeddings[0]) if new_embeddings else 0
        if dimension_checked:
            if batch_dimension and batch_dimension != new_dimension:
                raise RuntimeError(
                    f"{collection_name} 批次向量维度漂移: "
                    f"{batch_dimension} != {new_dimension}（第 {i} 条起）；"
                    "已保留原库，请排查嵌入模型输出后重跑脚本"
                )

        if not dimension_checked:
            dimension_checked = True
            new_dimension = batch_dimension
            if (
                current_dimension
                and new_dimension
                and current_dimension != new_dimension
            ):
                logger.warning(
                    "%s 向量维度变化: %s -> %s",
                    collection_name,
                    current_dimension,
                    new_dimension,
                )
                if dry_run:
                    logger.info(
                        "[dry-run] 实际执行时会把新维度向量写入临时 collection，"
                        "全部写完后换名为 %s",
                        collection_name,
                    )
                else:
                    write_target = _begin_dimension_migration(
                        client, collection_name, collection.metadata
                    )
                    staging_collection = write_target
                    migration_dimension = new_dimension

        if not dry_run:
            # upsert 覆写：ID 不变，document 和 metadata 不变，仅更新 embedding；
            # 维度迁移时写入临时 collection，原库保持不动
            write_target.upsert(
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

    if staging_collection is not None:
        _finish_dimension_migration(
            client,
            collection_name,
            staging_collection,
            expected_count=total,
            expected_dimension=migration_dimension,
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
    """根据 config.toml 构建 Embedder 实例（使用 cognitive 功能实际生效的配置）。"""
    embedding_config: EmbeddingModelConfig = config.resolve_embedding_model("cognitive")
    if not embedding_config.api_url or not embedding_config.model_name:
        logger.error(
            "config.toml 中 [models.embedding]（或 "
            "[models.embedding.features.cognitive]）未配置 api_url 或 model_name，无法继续。"
        )
        sys.exit(1)

    token_storage = TokenUsageStorage()
    model_requester = ModelRequester(None, token_storage)
    embedder = Embedder(model_requester, embedding_config, batch_size=64)
    embedder.start()
    return embedder


async def _main(args: argparse.Namespace) -> None:
    config = Config.load(strict=False)

    db_path = args.db_path or config.cognitive.vector_store_path
    logger.info("ChromaDB 路径: %s", db_path)
    cognitive_embedding = config.resolve_embedding_model("cognitive")
    logger.info(
        "嵌入模型: %s (dimensions=%s)",
        cognitive_embedding.model_name,
        cognitive_embedding.dimensions or "auto",
    )

    if not Path(db_path).exists():
        logger.error("ChromaDB 目录不存在: %s", db_path)
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(db_path))
    embedder = _build_embedder(config)

    total_processed = 0

    try:
        if not args.profiles_only:
            _recover_stale_staging(client, "cognitive_events")
            events_col = client.get_or_create_collection(
                "cognitive_events", metadata={"hnsw:space": "cosine"}
            )
            total_processed += await _reembed_collection(
                events_col,
                "cognitive_events",
                embedder,
                args.batch_size,
                args.dry_run,
                client,
            )

        if not args.events_only:
            _recover_stale_staging(client, "cognitive_profiles")
            profiles_col = client.get_or_create_collection(
                "cognitive_profiles", metadata={"hnsw:space": "cosine"}
            )
            total_processed += await _reembed_collection(
                profiles_col,
                "cognitive_profiles",
                embedder,
                args.batch_size,
                args.dry_run,
                client,
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
