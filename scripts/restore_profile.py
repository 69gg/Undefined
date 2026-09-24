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

恢复只改侧写 Markdown 文件与历史快照，不会重建 ChromaDB 中的侧写向量；如需同时刷新
检索向量，请按 docs/cognitive-memory.md 的说明重嵌入。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 将项目 src 加入 sys.path，使脚本可以直接 uv run 执行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PROJECT_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from Undefined.cognitive.profile_storage import ProfileStorage  # noqa: E402
from Undefined.config.loader import Config  # noqa: E402

logger = logging.getLogger("restore_profile")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="认知记忆侧写历史版本查看与恢复",
    )
    parser.add_argument(
        "action",
        choices=("list", "show", "restore"),
        help="list=列出历史版本；show=查看版本内容；restore=恢复版本",
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
        help="侧写目录（默认读取 config.toml 中的 cognitive.profiles_path）",
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

    # restore
    content = await storage.read_revision(entity_type, entity_id, args.revision)
    if content is None:
        logger.error("历史版本不存在: %s:%s/%s", entity_type, entity_id, args.revision)
        sys.exit(1)
    if args.dry_run:
        print(
            f"[dry-run] 将把 {entity_type}:{entity_id} 恢复为 {args.revision}，"
            f"当前内容会先存为新快照。"
        )
        print("---- 恢复后的内容 ----")
        print(content)
        return
    restored = await storage.restore_revision(entity_type, entity_id, args.revision)
    print(f"已恢复 {entity_type}:{entity_id} 到历史版本 {restored}")
    print("当前内容已另存为新快照，可再次用 list / restore 回退。")


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
