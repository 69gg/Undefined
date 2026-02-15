from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_RESULTS = 500


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """按 glob 模式匹配工作区内的文件。支持过滤和排序。"""

    pattern = str(args.get("pattern", "")).strip()
    base_path_rel = str(args.get("base_path", "")).strip()
    min_size = args.get("min_size")
    max_size = args.get("max_size")
    modified_after_str = args.get("modified_after")
    sort_by = str(args.get("sort_by", "name")).strip().lower()
    reverse = bool(args.get("reverse", False))

    if not pattern:
        return "错误：pattern 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    ws_resolved = workspace.resolve()

    if base_path_rel:
        search_root = (workspace / base_path_rel).resolve()
        if not str(search_root).startswith(str(ws_resolved)):
            return "错误：base_path 越界"
        if not search_root.is_dir():
            return f"错误：base_path 不存在或不是目录: {base_path_rel}"
    else:
        search_root = ws_resolved

    # 解析 modified_after
    modified_after_ts: float | None = None
    if modified_after_str:
        try:
            dt = datetime.fromisoformat(str(modified_after_str))
            modified_after_ts = dt.timestamp()
        except Exception:
            return f"错误：modified_after 格式无效: {modified_after_str}"

    try:
        # 收集匹配的文件及其元信息
        file_info: list[tuple[str, int, float]] = []  # (rel_path, size, mtime)

        for p in search_root.glob(pattern):
            if not str(p.resolve()).startswith(str(ws_resolved)):
                continue
            if not p.is_file():
                continue

            try:
                stat = p.stat()
                size = stat.st_size
                mtime = stat.st_mtime

                # 应用过滤条件
                if min_size is not None and size < int(min_size):
                    continue
                if max_size is not None and size > int(max_size):
                    continue
                if modified_after_ts is not None and mtime < modified_after_ts:
                    continue

                rel = str(p.relative_to(ws_resolved))
                file_info.append((rel, size, mtime))

                if len(file_info) >= MAX_RESULTS:
                    break
            except Exception:
                continue

        if not file_info:
            return "未找到匹配文件"

        # 排序
        if sort_by == "size":
            file_info.sort(key=lambda x: x[1], reverse=reverse)
        elif sort_by == "mtime":
            file_info.sort(key=lambda x: x[2], reverse=reverse)
        else:  # name
            file_info.sort(key=lambda x: x[0], reverse=reverse)

        # 格式化输出
        if sort_by == "name":
            # 仅显示文件名
            matches = [info[0] for info in file_info]
            result = "\n".join(matches)
        else:
            # 显示文件名和元信息
            lines: list[str] = []
            for rel_path, size, mtime in file_info:
                if sort_by == "size":
                    lines.append(f"{rel_path} ({size} bytes)")
                else:  # mtime
                    mtime_str = datetime.fromtimestamp(mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    lines.append(f"{rel_path} ({mtime_str})")
            result = "\n".join(lines)

        if len(file_info) >= MAX_RESULTS:
            result += f"\n\n... (结果已截断，共显示 {MAX_RESULTS} 条)"
        return result

    except Exception as exc:
        logger.exception("glob 匹配失败: %s", pattern)
        return f"glob 匹配失败: {exc}"
