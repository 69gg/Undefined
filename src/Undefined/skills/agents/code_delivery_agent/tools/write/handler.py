from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


def _get_file_lock(context: dict[str, Any], file_path: str) -> asyncio.Lock:
    """获取指定文件的锁，防止并发写入竞态。"""
    locks: dict[str, asyncio.Lock] | None = context.get("_write_file_locks")
    if locks is None:
        locks = {}
        context["_write_file_locks"] = locks

    if file_path not in locks:
        locks[file_path] = asyncio.Lock()

    return locks[file_path]


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """写入文件到工作区。支持多种写入模式。"""

    rel_path = str(args.get("path", "")).strip()
    mode = str(args.get("mode", "overwrite")).strip().lower()

    if not rel_path:
        return "错误：path 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    full_path = (workspace / rel_path).resolve()
    if not str(full_path).startswith(str(workspace.resolve())):
        return "错误：路径越界，只能写入 /workspace 下的文件"

    # 获取文件锁，防止并发写入竞态
    lock = _get_file_lock(context, str(full_path))

    async with lock:
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)

            if mode == "overwrite":
                content = str(args.get("content", ""))
                async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                    await f.write(content)
                byte_count = len(content.encode("utf-8"))
                return f"已写入 {byte_count} 字节到 {rel_path}"

            elif mode == "append":
                content = str(args.get("content", ""))
                async with aiofiles.open(full_path, "a", encoding="utf-8") as f:
                    await f.write(content)
                byte_count = len(content.encode("utf-8"))
                return f"已追加 {byte_count} 字节到 {rel_path}"

            elif mode == "replace":
                old_string = args.get("old_string")
                new_string = args.get("new_string")
                if old_string is None or new_string is None:
                    return "错误：replace 模式需要 old_string 和 new_string 参数"

                old_string = str(old_string)
                new_string = str(new_string)

                if not full_path.exists():
                    return f"错误：文件不存在: {rel_path}"

                async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                    original = await f.read()

                count = original.count(old_string)
                if count == 0:
                    return "错误：未找到要替换的字符串"
                if count > 1:
                    return f"错误：找到 {count} 处匹配，old_string 必须唯一"

                new_content = original.replace(old_string, new_string)
                async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                    await f.write(new_content)

                return f"已替换 {rel_path} 中的字符串（{len(old_string)} -> {len(new_string)} 字符）"

            elif mode == "insert_at_line":
                content = str(args.get("content", ""))
                line_number = args.get("line_number")
                if line_number is None:
                    return "错误：insert_at_line 模式需要 line_number 参数"

                line_number = int(line_number)
                if line_number < 0:
                    return "错误：line_number 必须 >= 0"

                if full_path.exists():
                    async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                        lines = (await f.read()).splitlines(keepends=True)
                else:
                    lines = []

                # 确保 content 以换行符结尾（如果它不是空的）
                if content and not content.endswith("\n"):
                    content += "\n"

                if line_number == 0:
                    lines.insert(0, content)
                elif line_number > len(lines):
                    # 如果行号超出范围，追加到末尾
                    lines.append(content)
                else:
                    lines.insert(line_number - 1, content)

                new_content = "".join(lines)
                async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                    await f.write(new_content)

                return f"已在 {rel_path} 第 {line_number} 行插入内容"

            else:
                return f"错误：未知的写入模式: {mode}"

        except Exception as exc:
            logger.exception("写入文件失败: %s", rel_path)
            return f"写入文件失败: {exc}"
