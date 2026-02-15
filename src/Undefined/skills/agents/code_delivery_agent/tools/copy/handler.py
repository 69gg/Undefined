from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """复制或移动文件/目录。"""

    source_rel = str(args.get("source", "")).strip()
    dest_rel = str(args.get("destination", "")).strip()
    mode = str(args.get("mode", "copy")).strip().lower()
    overwrite = bool(args.get("overwrite", False))

    if not source_rel:
        return "错误：source 不能为空"
    if not dest_rel:
        return "错误：destination 不能为空"
    if mode not in ("copy", "move"):
        return f"错误：未知的操作模式: {mode}"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    ws_resolved = workspace.resolve()
    source_path = (workspace / source_rel).resolve()
    dest_path = (workspace / dest_rel).resolve()

    # 路径安全检查
    if not str(source_path).startswith(str(ws_resolved)):
        return "错误：source 路径越界"
    if not str(dest_path).startswith(str(ws_resolved)):
        return "错误：destination 路径越界"

    if not source_path.exists():
        return f"源路径不存在: {source_rel}"

    # 检查目标是否已存在
    if dest_path.exists() and not overwrite:
        return f"目标已存在: {dest_rel}（设置 overwrite=true 以覆盖）"

    try:
        if mode == "copy":
            if source_path.is_dir():
                # 复制目录
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.copytree(source_path, dest_path)
                return f"已复制目录: {source_rel} -> {dest_rel}"
            else:
                # 复制文件
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, dest_path)
                return f"已复制文件: {source_rel} -> {dest_rel}"
        else:  # move
            # 移动文件或目录
            if dest_path.exists():
                if dest_path.is_dir():
                    shutil.rmtree(dest_path)
                else:
                    dest_path.unlink()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(dest_path))
            return f"已移动: {source_rel} -> {dest_rel}"

    except Exception as exc:
        logger.exception("%s 操作失败: %s -> %s", mode, source_rel, dest_rel)
        return f"{mode} 操作失败: {exc}"
