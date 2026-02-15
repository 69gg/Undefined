import hashlib
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _format_result(result: dict[str, str]) -> str:
    """将分析结果字典格式化为文本。"""
    lines: list[str] = []
    if result.get("description"):
        lines.append(f"描述：{result['description']}")
    if result.get("ocr_text"):
        lines.append(f"OCR：{result['ocr_text']}")
    if result.get("transcript"):
        lines.append(f"转写：{result['transcript']}")
    if result.get("subtitles"):
        lines.append(f"字幕：{result['subtitles']}")
    return "\n".join(lines)


def _hash_file(path: Path) -> str:
    """按块计算文件 SHA256，避免一次性读入大文件。"""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _build_media_history_key(path: Path, context: Dict[str, Any]) -> str:
    """构建带会话作用域的媒体历史键，避免同名文件冲突。"""
    group_id = context.get("group_id")
    user_id = context.get("user_id")
    if group_id is not None:
        scope = f"group:{group_id}"
    elif user_id is not None:
        scope = f"user:{user_id}"
    else:
        scope = "global"

    try:
        digest = _hash_file(path)
        return f"{scope}|sha256:{digest}"
    except Exception as e:
        logger.warning("计算媒体文件哈希失败，降级使用绝对路径作为键: %s", e)
        return f"{scope}|path:{path.resolve()}"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """利用 AI 对文件进行多模态分析（图片文字提取、内容描述等）"""
    file_path: str = args.get("file_path", "")
    media_type: str = args.get("media_type", "auto")
    prompt_extra: str = args.get("prompt", "")
    force_analyze: bool = args.get("force_analyze", False)

    path = Path(file_path)

    if not path.exists():
        return f"错误：文件不存在 {file_path}"

    if not path.is_file():
        return f"错误：{file_path} 不是文件"

    ai_client = context.get("ai_client")
    if not ai_client:
        return "错误：AI client 未在上下文中提供"

    media_history_key = _build_media_history_key(path, context)

    # ── 非强制模式下，优先返回历史 Q&A 供 AI 判断 ──
    if not force_analyze:
        history: list[dict[str, str]] = ai_client.get_media_history(media_history_key)
        if history:
            lines: list[str] = [f"【该文件已有 {len(history)} 条历史分析记录】"]
            for i, qa in enumerate(history, 1):
                lines.append(f"[{i}] 问：{qa['q']}")
                lines.append(f"    答：{qa['a']}")
            lines.append("")
            lines.append(
                "你可以根据以上历史记录直接回答用户。"
                "如果历史记录不足以回答，请再次调用本工具并设置 force_analyze=true 进行全新分析。"
            )
            return "\n".join(lines)

    # ── 执行真实的多模态分析 ──
    try:
        result = await ai_client.analyze_multimodal(
            str(path), media_type=media_type, prompt_extra=prompt_extra
        )
        if isinstance(result, dict):
            formatted = _format_result(result)
            if not formatted:
                return "分析失败"

            # 保存本次 Q&A 到历史
            question = prompt_extra or "（常规分析）"
            await ai_client.save_media_history(media_history_key, question, formatted)

            return formatted
        return str(result) if result else "分析失败"

    except Exception as e:
        logger.exception(f"多模态分析失败: {e}")
        return "多模态分析失败，请稍后重试"
