import chardet
from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    # 支持两个参数名以实现兼容性
    file_path = args.get("file_path") or args.get("path", "")

    if not file_path:
        return "错误：文件路径不能为空"

    # 将 base_path 限制在 NagaAgent 子模块中
    base_path = context.get("base_path", Path.cwd() / "code" / "NagaAgent")
    base_path = Path(base_path).resolve()

    # 解析相对于 base_path 的路径
    full_path = (base_path / file_path).resolve()

    # 安全检查
    if not str(full_path).startswith(str(base_path)):
        return "权限不足：只能读取当前工作目录下的文件"

    if not full_path.exists():
        return f"文件不存在: {file_path}"

    if full_path.is_dir():
        return f"错误：{file_path} 是一个目录，不是文件"

    try:
        with open(full_path, "rb") as binary_file:
            raw_data: bytes = binary_file.read()

        detected: Any = chardet.detect(raw_data)
        encoding: str | None = detected.get("encoding", "utf-8")
        confidence: float = detected.get("confidence", 0)

        if encoding is None or confidence < 0.5:
            encoding = "utf-8"

        file_content: str = ""
        try:
            file_content = raw_data.decode(encoding)
        except UnicodeDecodeError:
            try:
                file_content = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    file_content = raw_data.decode("utf-16")
                except UnicodeDecodeError:
                    file_content = raw_data.decode("latin-1")
                    logger.warning(
                        f"文件 {file_path} 使用 latin-1 解码，可能包含乱码。"
                    )

        if len(file_content) > 10000:
            file_content = file_content[:10000] + "\n... (内容过长，已截断)"

        return file_content

    except Exception as e:
        logger.exception(f"读取文件 {file_path} 时出错")
        return f"读取文件失败: {e}"
