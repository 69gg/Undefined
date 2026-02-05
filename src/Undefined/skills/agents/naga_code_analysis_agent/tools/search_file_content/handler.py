import re
from pathlib import Path
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在文件内容中搜索特定关键词或正则表达式模式"""
    pattern = args.get("pattern", "")
    path_str = args.get("path")
    include = args.get("include")

    # 将 base_path 限制在 NagaAgent 子模块中
    base_path = context.get("base_path", Path.cwd() / "code" / "NagaAgent")
    base_path = Path(base_path).resolve()

    if not path_str:
        full_path = base_path
    else:
        full_path = (base_path / path_str).resolve()

    if include is None:
        include = ""

    if not str(full_path).startswith(str(base_path)):
        return "权限不足：只能在当前工作目录下搜索"

    if not pattern:
        return "未提供搜索模式"

    try:
        regex = re.compile(pattern)
    except re.error:
        return f"无效的正则表达式: {pattern}"

    def iter_files(root: Path) -> list[Path]:
        if root.is_file():
            return [root]
        return [p for p in root.rglob("*") if p.is_file()]

    def include_match(path: Path) -> bool:
        if not include:
            return True
        return path.match(include) or path.name == include

    matches: list[str] = []
    try:
        for file_path in iter_files(full_path):
            if not include_match(file_path):
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for idx, line in enumerate(f, start=1):
                        if regex.search(line):
                            rel = file_path.relative_to(base_path).as_posix()
                            matches.append(f"{rel}:{idx}:{line.rstrip()}")
                            if len(matches) >= 50:
                                return "\n".join(matches)
            except OSError:
                continue
        if not matches:
            return f"未找到匹配: {pattern}"
        return "\n".join(matches)
    except Exception:
        return "工具执行出错: search_file_content"
