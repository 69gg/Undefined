from __future__ import annotations

import asyncio
import difflib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def _get_git_head_content(
    container_name: str, rel_path: str, timeout: int = 30
) -> str | None:
    """从 git HEAD 获取文件内容。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            container_name,
            "bash",
            "-lc",
            f"git show HEAD:{rel_path}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return stdout_b.decode("utf-8", errors="replace")
        return None
    except Exception:
        return None


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """查看文件差异。"""

    path1_rel = str(args.get("path1", "")).strip()
    path2_rel = str(args.get("path2", "")).strip()
    context_lines = int(args.get("context_lines", 3))

    if not path1_rel:
        return "错误：path1 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    ws_resolved = workspace.resolve()
    path1 = (workspace / path1_rel).resolve()

    # 路径安全检查
    if not str(path1).startswith(str(ws_resolved)):
        return "错误：path1 路径越界"

    if not path1.exists():
        return f"文件不存在: {path1_rel}"
    if path1.is_dir():
        return f"错误：{path1_rel} 是目录，不是文件"

    try:
        # 读取第一个文件
        with open(path1, "r", encoding="utf-8", errors="replace") as f:
            content1 = f.read()
        lines1 = content1.splitlines(keepends=True)

        # 确定第二个文件的内容
        if path2_rel:
            # 对比两个文件
            path2 = (workspace / path2_rel).resolve()
            if not str(path2).startswith(str(ws_resolved)):
                return "错误：path2 路径越界"
            if not path2.exists():
                return f"文件不存在: {path2_rel}"
            if path2.is_dir():
                return f"错误：{path2_rel} 是目录，不是文件"

            with open(path2, "r", encoding="utf-8", errors="replace") as f:
                content2 = f.read()
            lines2 = content2.splitlines(keepends=True)

            fromfile = path1_rel
            tofile = path2_rel
        else:
            # 对比文件与 git HEAD
            container_name: str | None = context.get("container_name")
            if not container_name:
                return "错误：容器未启动"

            git_content = await _get_git_head_content(container_name, path1_rel)
            if git_content is None:
                return "无法获取 git HEAD 版本（可能不是 git 仓库或文件不在 HEAD 中）"

            lines2 = git_content.splitlines(keepends=True)
            fromfile = f"HEAD:{path1_rel}"
            tofile = path1_rel

        # 生成 unified diff
        diff_lines = list(
            difflib.unified_diff(
                lines2,
                lines1,
                fromfile=fromfile,
                tofile=tofile,
                lineterm="",
                n=context_lines,
            )
        )

        if not diff_lines:
            return "文件内容相同，无差异"

        result = "\n".join(diff_lines)
        return result

    except Exception as exc:
        logger.exception("diff 操作失败: %s", path1_rel)
        return f"diff 操作失败: {exc}"
