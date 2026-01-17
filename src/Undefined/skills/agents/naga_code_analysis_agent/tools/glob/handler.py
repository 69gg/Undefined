import subprocess
from pathlib import Path
from typing import Any, Dict


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "")

    # 将 base_path 限制在 NagaAgent 子模块中
    base_path = context.get("base_path", Path.cwd() / "code" / "NagaAgent")
    base_path = Path(base_path).resolve()

    path = str(base_path)

    cmd = ["find", path, "-type", "f", "-name", pattern]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            files = result.stdout.strip().split("\n")
            relative_files = [str(Path(f).relative_to(base_path)) for f in files if f]
            if len(relative_files) > 100:
                relative_files = relative_files[:100] + [
                    f"... 还有 {len(relative_files) - 100} 个文件"
                ]
            return "\n".join(relative_files)
        else:
            return f"未找到匹配的文件: {pattern}"

    except subprocess.TimeoutExpired:
        return "工具执行超时: glob"
