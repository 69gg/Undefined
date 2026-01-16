from typing import Any, Dict
import httpx
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    prompt = args.get("prompt")
    model = args.get("model", "anything-v5") # Default model guess
    size = args.get("size", "1:1")
    target_id = args.get("target_id")
    message_type = args.get("message_type")
    
    url = "https://api.xingzhige.com/API/DrawOne/"
    params = {
        "prompt": prompt,
        "model": model,
        "size": size
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client: # AI draw might take time
            response = await client.get(url, params=params)
            
            try:
                data = response.json()
            except Exception:
                return f"API 返回错误 (非JSON): {response.text[:100]}"
            
            # Parse response
            # The docs say "Returns: Json". It likely contains a "url" or "image" field.
            # I will assume 'url' or similar.
            # If I can't find a URL, I'll return the JSON to the user to debug.
            
            image_url = data.get("url") or data.get("image") or data.get("img")
            
            if not image_url and "data" in data and isinstance(data["data"], str):
                 image_url = data["data"]

            if not image_url:
                return f"未找到图片链接: {data}"
            
            # Download Image
            img_response = await client.get(image_url)
            img_response.raise_for_status()
            
            filename = f"ai_draw_{uuid.uuid4().hex[:8]}.jpg"
            filepath = Path.cwd() / "img" / filename
            filepath.parent.mkdir(exist_ok=True)
            
            with open(filepath, "wb") as f:
                f.write(img_response.content)
            
            send_image_callback = context.get("send_image_callback")
            if send_image_callback:
                await send_image_callback(target_id, message_type, str(filepath))
                return f"AI 绘图已发送给 {message_type} {target_id}"
            else:
                return "发送图片回调未设置"

    except Exception as e:
        logger.exception(f"AI 绘图失败: {e}")
        return f"AI 绘图失败: {e}"
