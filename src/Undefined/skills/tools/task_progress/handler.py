from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

STATUS_ICONS: Dict[str, str] = {
    "pending": "⬚",
    "in_progress": "▶",
    "done": "✔",
    "skipped": "⊘",
}

VALID_STATUSES = frozenset(STATUS_ICONS.keys())


def _parse_task_id(value: Any) -> int | None:
    """将任务 ID 解析为整数；非法时返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None
    return None


def _format_task_list(tasks: list[dict[str, Any]]) -> str:
    """将任务列表格式化为可读文本。"""
    if not tasks:
        return "（无任务）"

    lines: list[str] = []
    done_count = sum(1 for t in tasks if t.get("status") == "done")
    total = len(tasks)
    lines.append(f"进度: {done_count}/{total}")
    lines.append("")

    for task in tasks:
        icon = STATUS_ICONS.get(task.get("status", "pending"), "⬚")
        tid = task.get("id", "?")
        desc = task.get("description", "")
        lines.append(f"  {icon} [{tid}] {desc}")

    return "\n".join(lines)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """任务进度追踪工具。"""
    action = args.get("action", "")
    tasks_input = args.get("tasks")

    if action not in ("plan", "update"):
        return "action 必须是 plan 或 update"

    if not isinstance(tasks_input, list) or len(tasks_input) == 0:
        return "tasks 必须是非空数组"

    # 从 context 获取或初始化任务列表
    task_store: list[dict[str, Any]] = context.get("_task_progress", [])

    if action == "plan":
        # 创建/替换计划
        new_tasks: list[dict[str, Any]] = []
        for item in tasks_input:
            tid_raw = item.get("id")
            desc = item.get("description", "")
            tid = _parse_task_id(tid_raw)
            if tid is None:
                return f"plan 操作中 id 必须是整数，问题项: {item}"
            if not desc:
                return f"plan 操作要求每个步骤都有 id 和 description，问题项: {item}"
            status = item.get("status", "pending")
            if status not in VALID_STATUSES:
                status = "pending"
            new_tasks.append({"id": tid, "description": desc, "status": status})

        # 按 id 排序
        new_tasks.sort(key=lambda t: t.get("id", 0))
        task_store = new_tasks
        context["_task_progress"] = task_store

        logger.info(f"[task_progress] 创建计划，共 {len(task_store)} 个步骤")
        return f"计划已创建\n{_format_task_list(task_store)}"

    # action == "update"
    if not task_store:
        return "还没有任务计划，请先用 plan 动作创建"

    # 构建 id -> index 映射
    id_to_idx = {t["id"]: i for i, t in enumerate(task_store)}

    updated: list[int] = []
    for item in tasks_input:
        tid_raw = item.get("id")
        new_status = item.get("status")
        tid = _parse_task_id(tid_raw)
        if tid is None:
            return f"update 操作中 id 必须是整数，问题项: {item}"
        if new_status is None:
            return f"update 操作要求每个项都有 id 和 status，问题项: {item}"
        if new_status not in VALID_STATUSES:
            return f"无效的 status: {new_status}，可选: {', '.join(VALID_STATUSES)}"

        idx = id_to_idx.get(tid)
        if idx is None:
            return f"不存在 id={tid} 的步骤"

        task_store[idx]["status"] = new_status
        # 允许更新描述
        new_desc = item.get("description")
        if new_desc:
            task_store[idx]["description"] = new_desc
        updated.append(tid)

    context["_task_progress"] = task_store

    logger.info(f"[task_progress] 更新步骤 {updated}")
    return f"已更新步骤 {updated}\n{_format_task_list(task_store)}"
