from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


def _todo_path(context: dict[str, Any]) -> Path:
    task_dir: Path = context["task_dir"]
    return task_dir / "todo.json"


async def _load_todos(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            data = json.loads(await f.read())
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def _save_todos(path: Path, todos: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(todos, ensure_ascii=False, indent=2))


def _next_id(todos: list[dict[str, Any]]) -> int:
    if not todos:
        return 1
    return int(max(item.get("id", 0) for item in todos)) + 1


def _format_todos(todos: list[dict[str, Any]]) -> str:
    if not todos:
        return "待办列表为空"
    status_icons = {"pending": "⬜", "in_progress": "🔄", "done": "✅"}
    lines: list[str] = []
    for item in todos:
        icon = status_icons.get(item.get("status", "pending"), "⬜")
        lines.append(f"{icon} [{item['id']}] {item['content']} ({item['status']})")
    return "\n".join(lines)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """记录与追踪任务待办和进度。"""

    action = str(args.get("action", "")).strip().lower()
    if not action:
        return "错误：action 不能为空"

    if "task_dir" not in context:
        return "错误：task_dir 未设置"

    path = _todo_path(context)
    todos = await _load_todos(path)

    if action == "list":
        return _format_todos(todos)

    if action == "add":
        content = str(args.get("content", "")).strip()
        if not content:
            return "错误：add 操作需要 content"
        new_item = {"id": _next_id(todos), "content": content, "status": "pending"}
        todos.append(new_item)
        await _save_todos(path, todos)
        return f"已添加: [{new_item['id']}] {content}"

    if action == "update":
        item_id = args.get("item_id")
        if item_id is None:
            return "错误：update 操作需要 item_id"
        item_id = int(item_id)
        status = str(args.get("status", "in_progress")).strip()
        for item in todos:
            if item["id"] == item_id:
                item["status"] = status
                await _save_todos(path, todos)
                return f"已更新: [{item_id}] -> {status}"
        return f"未找到 ID={item_id} 的待办项"

    if action == "remove":
        item_id = args.get("item_id")
        if item_id is None:
            return "错误：remove 操作需要 item_id"
        item_id = int(item_id)
        original_len = len(todos)
        todos = [item for item in todos if item["id"] != item_id]
        if len(todos) == original_len:
            return f"未找到 ID={item_id} 的待办项"
        await _save_todos(path, todos)
        return f"已删除 ID={item_id}"

    if action == "clear":
        await _save_todos(path, [])
        return "待办列表已清空"

    return f"未知操作: {action}"
