from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    media_url = args.get("media_url", "")
    media_type = args.get("media_type", "auto")
    prompt = args.get("prompt", "")
    
    if not media_url:
        return "媒体文件 URL/ID 不能为空"
    
    ai_client = context.get("ai_client")
    get_image_url_callback = context.get("get_image_url_callback")
    
    # Resolve file_id to URL if needed
    if media_url and not (media_url.startswith("http") or media_url.startswith("data:")):
        if get_image_url_callback:
            logger.info(f"解析媒体文件 ID: {media_url}")
            resolved_url = await get_image_url_callback(media_url)
            if resolved_url:
                media_url = resolved_url
            else:
                return f"错误：无法将媒体文件 ID {media_url} 解析为有效 URL"
    
    if ai_client:
        res = await ai_client.analyze_multimodal(media_url, media_type, prompt)
        desc = res.get("description", "分析失败")
        
        # 根据媒体类型返回相应的结果
        if media_type == "image" or (media_type == "auto" and res.get("ocr_text") is not None):
            ocr = res.get("ocr_text", "")
            return f"图片描述：{desc}\nOCR文字：{ocr}"
        elif media_type == "audio" or (media_type == "auto" and res.get("transcript") is not None):
            transcript = res.get("transcript", "")
            return f"音频分析：{desc}\n转写内容：{transcript}"
        elif media_type == "video" or (media_type == "auto" and res.get("subtitles") is not None):
            subtitles = res.get("subtitles", "")
            return f"视频分析：{desc}\n字幕内容：{subtitles}"
        else:
            # 默认返回描述
            return f"媒体分析：{desc}"
    else:
        return "AI Client 未在上下文中提供，无法分析媒体内容"