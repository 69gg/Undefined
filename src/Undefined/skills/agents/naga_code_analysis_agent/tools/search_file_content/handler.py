import subprocess
from pathlib import Path
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
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

    cmd = ["grep", "-rn", pattern, str(full_path)]
    if include:
        cmd.extend(["--include", include])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            output = result.stdout
            lines = output.split("\n")[:50]
            return "\n".join(lines)
        else:
            return f"未找到匹配: {pattern}"

    except subprocess.TimeoutExpired:
        return "工具执行超时: search_file_content"
