from typing import Any, Dict
import httpx
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    msg = args.get("msg")
    n = args.get("n", 5)

    url = "https://api.xingzhige.com/API/b_search/"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params={"msg": msg, "n": n})
            response.raise_for_status()
            data = response.json()

            # API 返回一个以 0, 1, 2... 为键的字典来表示列表？
            # 或者是一个字典列表？
            # 根据 'n'，它可能返回一个列表或字典索引。
            # 让我们同时处理这两种情况。

            results = []
            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                # 检查是否为索引键 "0", "1" 等。
                if "0" in data:
                    for i in range(len(data)):
                        key = str(i)
                        if key in data:
                            results.append(data[key])
                elif "code" in data and data["code"] != 200:
                    return f"搜索失败: {data.get('msg', '未知错误')}"
                else:
                    # 单个结果或非预期格式
                    results = [data]

            output = f"🔍 B站搜索 '{msg}' 结果:\n"
            for item in results:
                title = item.get("title")
                linktype = item.get("linktype")
                name = item.get("name")
                bvid = item.get("bvid")

                item_str = ""
                if linktype and title:
                    item_str += f"- [{linktype}] {title}\n"
                elif title:
                    item_str += f"- {title}\n"

                if name:
                    item_str += f"  UP主: {name}\n"

                if bvid:
                    url_link = f"https://www.bilibili.com/video/{bvid}"
                    item_str += f"  链接: {url_link}\n"

                if item_str:
                    output += item_str + "\n"

            return output

    except Exception as e:
        logger.exception(f"B站搜索失败: {e}")
        return f"B站搜索失败: {e}"
