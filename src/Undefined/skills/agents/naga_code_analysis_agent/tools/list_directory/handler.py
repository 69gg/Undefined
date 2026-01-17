from pathlib import Path
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    path_str = args.get("path")
    # 将 base_path 限制在 NagaAgent 子模块中
    base_path = context.get("base_path", Path.cwd() / "code" / "NagaAgent")
    base_path = Path(base_path).resolve()

    if not path_str:
        full_path = base_path
    else:
        # 解析相对于 base_path 的路径
        full_path = (base_path / path_str).resolve()

    if not str(full_path).startswith(str(base_path)):
        return f"权限不足：只能列出当前工作目录下的内容 ({base_path})"

    if not full_path.exists():
        return f"目录不存在: {path_str}"

    items = []
    for item in full_path.iterdir():
        item_type = "📁 " if item.is_dir() else "📄 "
        items.append(f"{item_type}{item.name}")

    if len(items) > 100:
        items = items[:100] + [f"... 还有 {len(items) - 100} 项"]

    return "\n".join(items)
