from pathlib import Path
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """利用 AI 对文件进行多模态分析（图片文字提取、内容描述等）"""
    file_path: str = args.get("file_path", "")
    media_type: str = args.get("media_type", "auto")
    prompt_extra: str = args.get("prompt", "")

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    ai_client = context.get("ai_client")
    if not ai_client:
        return "错误：AI client 未在上下文中提供"

    try:
        result = await ai_client.analyze_multimodal(
            str(path), media_type=media_type, prompt_extra=prompt_extra
        )
        if isinstance(result, dict):
            lines: list[str] = []
            description = result.get("description", "")
            ocr_text = result.get("ocr_text", "")
            transcript = result.get("transcript", "")
            subtitles = result.get("subtitles", "")
            if description:
                lines.append(f"描述：{description}")
            if ocr_text:
                lines.append(f"OCR：{ocr_text}")
            if transcript:
                lines.append(f"转写：{transcript}")
            if subtitles:
                lines.append(f"字幕：{subtitles}")
            return "\n".join(lines) if lines else "分析失败"
        return str(result) if result else "分析失败"

    except Exception as e:
        logger.exception(f"多模态分析失败: {e}")
        return "多模态分析失败，请稍后重试"
