from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info("获取今日黄金价格")

            response = await client.get("https://v2.xxapi.cn/api/goldprice")
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"获取黄金价格失败: {data.get('msg')}"

            price_data = data.get("data", {})
            result = "【今日黄金价格】\n\n"

            # 银行投资金条价格
            bank_gold = price_data.get("bank_gold_bar_price", [])
            if bank_gold:
                result += "【银行投资金条价格】\n"
                for item in bank_gold:
                    result += f"{item.get('bank', '')}: {item.get('price', '')}元/克\n"
                result += "\n"

            # 黄金回收价格
            recycle_price = price_data.get("gold_recycle_price", [])
            if recycle_price:
                result += "【黄金回收价格】\n"
                for item in recycle_price:
                    result += f"{item.get('gold_type', '')}: {item.get('recycle_price', '')}元/克 ({item.get('updated_date', '')})\n"
                result += "\n"

            # 贵金属品牌价格
            precious_metal = price_data.get("precious_metal_price", [])
            if precious_metal:
                result += "【贵金属品牌价格】\n"
                for item in precious_metal:
                    result += f"{item.get('brand', '')}:\n"
                    result += f"  金条价: {item.get('bullion_price', '')}元/克\n"
                    result += f"  黄金价: {item.get('gold_price', '')}元/克\n"
                    result += f"  铂金价: {item.get('platinum_price', '')}元/克\n"
                    result += f"  更新日期: {item.get('updated_date', '')}\n\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"获取黄金价格失败: {e}"
    except Exception as e:
        logger.exception(f"获取黄金价格失败: {e}")
        return f"获取黄金价格失败: {e}"
