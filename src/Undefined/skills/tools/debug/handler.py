import logging
import uuid
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 调试数据保存目录
DEBUG_DIR = Path("data/debug")


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """执行 debug 工具，保存调试信息到文本文件"""
    content = args.get("content", "")
    if not content:
        return "调试内容不能为空"

    # 确保目录存在
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    # 生成 UUID 作为文件名
    file_uuid = uuid.uuid4()
    filename = f"{file_uuid}.txt"
    filepath = DEBUG_DIR / filename

    # 保存到文件
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"调试信息已保存到: {filepath}")
        return f"调试信息已保存（UUID: {file_uuid}）"
    except Exception as e:
        logger.error(f"保存调试信息失败: {e}")
        return f"保存失败: {e}"
