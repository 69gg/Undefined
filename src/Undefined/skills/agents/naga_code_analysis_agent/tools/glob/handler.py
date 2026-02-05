from pathlib import Path
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """使用 glob 模式搜索匹配的文件"""
    pattern = args.get("pattern", "")

    # 将 base_path 限制在 NagaAgent 子模块中
    base_path = context.get("base_path", Path.cwd() / "code" / "NagaAgent")
    base_path = Path(base_path).resolve()

    if not pattern:
        return "未提供匹配模式"

    try:
        matches: list[str] = []
        for candidate in base_path.rglob(pattern):
            if not candidate.is_file():
                continue
            try:
                matches.append(str(candidate.relative_to(base_path)))
            except ValueError:
                continue

        if not matches:
            return f"未找到匹配的文件: {pattern}"

        if len(matches) > 100:
            matches = matches[:100] + [f"... 还有 {len(matches) - 100} 个文件"]
        return "\n".join(matches)
    except Exception:
        return "工具执行出错: glob"
