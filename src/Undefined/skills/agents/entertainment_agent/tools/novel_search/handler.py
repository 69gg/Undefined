from typing import Any, Dict
import logging

from Undefined.skills.http_client import get_text_with_retry
from Undefined.skills.http_config import get_jkyai_url

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在网络上搜索指定小说及其相关链接信息"""
    name = args.get("name")
    href = args.get("href")
    num = args.get("num")

    url = get_jkyai_url("/API/fqmfxs.php")
    params = {}
    if name:
        params["name"] = name
    if href:
        params["href"] = href
    if num:
        params["num"] = num

    try:
        # API 返回文本
        return await get_text_with_retry(
            url,
            params=params,
            default_timeout=15.0,
            context=context,
        )

    except Exception as e:
        logger.exception(f"小说工具操作失败: {e}")
        return f"小说工具操作失败: {e}"
