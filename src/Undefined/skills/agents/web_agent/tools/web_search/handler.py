from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    query = args.get("query", "")
    if not query:
        return "搜索关键词不能为空"

    search_wrapper = context.get("search_wrapper")
    if not search_wrapper:
        return "搜索功能未启用（SEARXNG_URL 未配置或 langchain_community 未安装）"

    num_results = args.get("num_results", 5)

    try:
        results = search_wrapper.run(query, num_results=num_results)

        if results:
            return f"搜索结果:\n{results}"
        else:
            return "搜索未返回结果"
    except Exception as e:
        logger.error(f"搜索执行失败: {e}")
        return f"搜索执行失败: {e}"
