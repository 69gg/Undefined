#!/usr/bin/env python3
"""认知记忆侧写历史版本的查看与恢复脚本。

侧写在每次写入前会把旧内容存成历史快照（默认保留 `cognitive.profile.revision_keep`
份），但历史快照此前只能手工 `ls` / `cp`，没有正式的读取与恢复入口。本脚本提供：

    # 列出某个用户/群聊的全部历史版本
    uv run python scripts/restore_profile.py list --entity-type user --entity-id 123456

    # 查看某个历史版本内容
    uv run python scripts/restore_profile.py show --entity-type user --entity-id 123456 --revision 20260101000000000000.md

    # 恢复某个历史版本（恢复前会把当前内容另存为新快照，可再次回退）
    uv run python scripts/restore_profile.py restore --entity-type user --entity-id 123456 --revision 20260101000000000000.md

    # 仅预览将要恢复的内容（不写盘）
    uv run python scripts/restore_profile.py restore --entity-type user --entity-id 123456 --revision 20260101000000000000.md --dry-run

恢复同时更新侧写 Markdown、历史快照和该实体的 ChromaDB 检索正文与向量。
若向量写入失败，可用 sync 动作从当前 Markdown 重试，不必再次恢复历史版本。
实际恢复或同步前，应停止机器人及其他写入侧写/向量库的进程。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# 将项目 src 加入 sys.path，使脚本可以直接 uv run 执行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from Undefined.cognitive.profile_storage import ProfileStorage  # noqa: E402
from Undefined.cognitive.service.helpers import (  # noqa: E402
    _build_profile_vector_payload,
    _current_profile_name,
    _normalize_profile_tags,
    _parse_profile_markdown,
)
from Undefined.config.loader import Config  # noqa: E402
from reembed_cognitive import _build_embedder, _open_chroma  # noqa: E402

logger = logging.getLogger("restore_profile")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="认知记忆侧写历史版本查看与恢复",
    )
    parser.add_argument(
        "action",
        choices=("list", "show", "restore", "sync"),
        help="list=列出历史版本；show=查看版本；restore=恢复并同步检索；sync=同步当前侧写检索",
    )
    parser.add_argument(
        "--db-path",
        default="",
        help="ChromaDB 目录（默认读取 config.toml 中的 cognitive.vector_store.path）",
    )
    parser.add_argument(
        "--entity-type",
        required=True,
        choices=("user", "group"),
        help="实体类型",
    )
    parser.add_argument("--entity-id", required=True, help="用户 ID 或群 ID")
    parser.add_argument(
        "--revision",
        default="",
        help="历史版本文件名（show / restore 必填，取值来自 list 输出）",
    )
    parser.add_argument(
        "--profiles-path",
        default="",
        help="侧写目录（默认读取 config.toml 中的 cognitive.profile.path）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的操作，不写盘",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    args = parser.parse_args()
    if args.action in {"show", "restore"} and not args.revision:
        parser.error("show / restore 需要 --revision")
    return args


def _print_revisions(revisions: list[str]) -> None:
    if not revisions:
        print("（暂无历史版本）")
        return
    for index, name in enumerate(revisions, start=1):
        print(f"{index:>3}. {name}")


def _vector_payload(
    content: str, entity_type: str, entity_id: str
) -> tuple[str, dict[str, Any]]:
    """沿用运行时侧写格式；无 frontmatter 的旧文件仍可同步正文。"""
    parsed = _parse_profile_markdown(content)
    if parsed is None:
        frontmatter: dict[str, Any] = {}
        evaluation, summary, roast = "", content, ""
    else:
        frontmatter, evaluation, summary, roast = parsed
    return _build_profile_vector_payload(
        entity_type=entity_type,
        entity_id=entity_id,
        effective_name=_current_profile_name(entity_type, frontmatter),
        tags=_normalize_profile_tags(frontmatter.get("tags")),
        summary=summary,
        evaluation=evaluation,
        roast=roast,
    )


async def _restore_and_sync(
    config: Config,
    storage: ProfileStorage,
    *,
    entity_type: str,
    entity_id: str,
    revision: str | None,
    document: str,
    metadata: dict[str, Any],
    db_path: Path,
) -> None:
    embedder = _build_embedder(config)
    try:
        # 模型请求失败时，尚未改动侧写文件和向量库。
        embeddings = await embedder.embed([document])
        if len(embeddings) != 1 or not embeddings[0]:
            raise RuntimeError("嵌入模型没有返回该侧写的有效向量，未恢复侧写")
        async with _open_chroma(db_path, dry_run=False) as client:
            collection = client.get_or_create_collection(
                "cognitive_profiles", metadata={"hnsw:space": "cosine"}
            )
            if revision is not None:
                await storage.restore_revision(entity_type, entity_id, revision)
            try:
                await asyncio.to_thread(
                    collection.upsert,
                    ids=[f"{entity_type}:{entity_id}"],
                    documents=[document],
                    embeddings=embeddings,
                    metadatas=[metadata],
                )
            except Exception as exc:
                raise RuntimeError(
                    "侧写检索同步失败；当前 Markdown 已保留。修复向量库/模型配置后，"
                    "使用 sync 动作重试当前侧写，无需再次恢复历史版本。"
                ) from exc
    finally:
        await embedder.stop()


async def _main(args: argparse.Namespace) -> None:
    config = Config.load(strict=False)
    base_path = args.profiles_path or config.cognitive.profiles_path
    storage = ProfileStorage(
        base_path,
        revision_keep=config.cognitive.profile_revision_keep,
    )
    entity_type = args.entity_type
    entity_id = args.entity_id

    if args.action == "list":
        revisions = await storage.list_revisions(entity_type, entity_id)
        print(f"侧写目录: {base_path}")
        print(f"实体: {entity_type}:{entity_id}")
        _print_revisions(revisions)
        return

    if args.action == "show":
        content = await storage.read_revision(entity_type, entity_id, args.revision)
        if content is None:
            logger.error(
                "历史版本不存在: %s:%s/%s", entity_type, entity_id, args.revision
            )
            sys.exit(1)
        print(content)
        return

    revision = args.revision if args.action == "restore" else None
    content = (
        await storage.read_revision(entity_type, entity_id, revision)
        if revision is not None
        else await storage.read_profile(entity_type, entity_id)
    )
    if content is None:
        logger.error(
            "侧写或历史版本不存在: %s:%s/%s", entity_type, entity_id, revision or "当前"
        )
        sys.exit(1)
    document, metadata = _vector_payload(content, entity_type, entity_id)
    db_path = Path(args.db_path or config.cognitive.vector_store_path)
    print(f"侧写目录: {base_path}")
    print(f"ChromaDB 目录: {db_path}")
    if args.dry_run:
        if revision is not None:
            print(
                f"[dry-run] 将把 {entity_type}:{entity_id} 恢复为 {revision}，"
                "当前内容会先存为新快照。"
            )
        print(f"[dry-run] 将同步 cognitive_profiles 中的 {entity_type}:{entity_id}")
        print("---- 恢复后的内容 ----")
        print(content)
        print("---- 检索正文 ----")
        print(document)
        return
    await _restore_and_sync(
        config,
        storage,
        entity_type=entity_type,
        entity_id=entity_id,
        revision=revision,
        document=document,
        metadata=metadata,
        db_path=db_path,
    )
    if revision is not None:
        print(f"已恢复 {entity_type}:{entity_id} 到历史版本 {revision}")
        print("当前内容已另存为新快照，可再次用 list / restore 回退。")
    print(f"已同步 {entity_type}:{entity_id} 的检索正文与向量。")


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
