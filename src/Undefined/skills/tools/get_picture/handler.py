from typing import Any, Dict
import logging
import httpx
import asyncio
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# API 地址映射
API_URLS = {
    "baisi": "https://v2.xxapi.cn/api/baisi",
    "heisi": "https://v2.xxapi.cn/api/heisi",
    "head": "https://v2.xxapi.cn/api/head",
    "jk": "https://v2.xxapi.cn/api/jk",
    "acg": "https://v2.xxapi.cn/api/randomAcgPic",
    "meinvpic": "https://v2.xxapi.cn/api/meinvpic",
    "wallpaper": "https://v2.xxapi.cn/api/wallpaper",
    "ys": "https://v2.xxapi.cn/api/ys",
    "historypic": "https://v2.xxapi.cn/api/historypic",
    "random4kPic": "https://v2.xxapi.cn/api/random4kPic",
}

# 图片类型名称映射
TYPE_NAMES = {
    "baisi": "白丝",
    "heisi": "黑丝",
    "head": "头像",
    "jk": "JK",
    "acg": "二次元",
    "meinvpic": "小姐姐",
    "wallpaper": "壁纸",
    "ys": "原神",
    "historypic": "历史上的今天",
    "random4kPic": "4K图片",
    "meitui": "美腿",
}


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    message_type = args.get("message_type")
    target_id = args.get("target_id")
    picture_type = args.get("picture_type", "acg")
    count = args.get("count", 1)
    device = args.get("device", "pc")
    fourk_type = args.get("fourk_type", "acg")

    # 参数验证
    if not message_type:
        return "❌ 消息类型不能为空"
    if message_type not in ["group", "private"]:
        return "❌ 消息类型必须是 group（群聊）或 private（私聊）"
    if not target_id:
        return "❌ 目标 ID 不能为空"
    if not isinstance(target_id, int):
        return "❌ 目标 ID 必须是整数"
    if picture_type not in API_URLS:
        return f"❌ 不支持的图片类型: {picture_type}\n支持的类型: {', '.join(TYPE_NAMES.values())}"
    if not isinstance(count, int):
        return "❌ 图片数量必须是整数"
    if count < 1 or count > 10:
        return "❌ 图片数量必须在 1-10 之间"
    if picture_type == "acg" and device not in ["pc", "wap"]:
        return "❌ 设备类型必须是 pc（电脑端）或 wap（手机端）"
    if picture_type == "random4kPic" and fourk_type not in ["acg", "wallpaper"]:
        return "❌ 4K图片类型必须是 acg（二次元）或 wallpaper（风景）"

    # 获取发送图片回调
    send_image_callback = context.get("send_image_callback")
    if not send_image_callback:
        return "发送图片回调未设置"

    # 构造请求参数
    params: Dict[str, Any] = {"return": "json"}
    if picture_type == "acg":
        params["type"] = device
    elif picture_type == "random4kPic":
        params["type"] = fourk_type

    # 获取图片
    success_count = 0
    fail_count = 0
    local_image_paths: list[str] = []

    # 创建图片保存目录
    img_dir = Path.cwd() / "img"
    img_dir.mkdir(exist_ok=True)

    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(count):
            try:
                logger.info(
                    f"正在获取第 {i + 1}/{count} 张 {TYPE_NAMES[picture_type]} 图片..."
                )
                response = await client.get(API_URLS[picture_type], params=params)
                response.raise_for_status()

                # 美腿类型直接返回 JPEG 图片，不需要解析 JSON
                if picture_type == "meitui":
                    # 验证响应内容类型
                    content_type = response.headers.get("content-type", "")
                    if "image" not in content_type.lower():
                        logger.error(f"响应不是图片格式: {content_type}")
                        fail_count += 1
                        continue

                    # 保存图片
                    filename = f"{picture_type}_{uuid.uuid4().hex[:16]}.jpg"
                    filepath = img_dir / filename
                    filepath.write_bytes(response.content)

                    logger.info(f"图片已保存到: {filepath}")
                    local_image_paths.append(str(filepath))
                    success_count += 1
                else:
                    data = response.json()

                    # 检查响应
                    if data.get("code") != 200:
                        logger.error(f"获取图片失败: {data.get('msg')}")
                        fail_count += 1
                        continue

                    # 获取图片 URL
                    image_url = data.get("data")
                    if not image_url:
                        logger.error("响应中未找到图片 URL")
                        fail_count += 1
                        continue

                    logger.info(f"图片 URL: {image_url}")

                    # 下载图片到本地
                    logger.info("正在下载图片到本地...")
                    image_response = await client.get(image_url, timeout=15.0)
                    image_response.raise_for_status()

                    # 保存图片
                    filename = f"{picture_type}_{uuid.uuid4().hex[:16]}.jpg"
                    filepath = img_dir / filename
                    filepath.write_bytes(image_response.content)

                    logger.info(f"图片已保存到: {filepath}")
                    local_image_paths.append(str(filepath))
                    success_count += 1

            except httpx.TimeoutException:
                logger.error(f"获取图片超时: {picture_type} 第 {i + 1} 张")
                fail_count += 1
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP 错误: {e}")
                fail_count += 1
            except Exception as e:
                logger.exception(f"获取图片失败: {e}")
                fail_count += 1

    # 如果没有获取到任何图片
    if success_count == 0:
        return f"获取 {TYPE_NAMES[picture_type]} 图片失败，请稍后重试"

    # 发送图片
    for idx, image_path in enumerate(local_image_paths, 1):
        try:
            logger.info(
                f"正在发送第 {idx}/{success_count} 张图片到 {message_type} {target_id}"
            )
            logger.info(f"图片路径: {image_path}")
            await send_image_callback(target_id, message_type, image_path)
            logger.info(f"图片 {idx} 发送成功")

            # 删除本地图片文件
            try:
                Path(image_path).unlink()
                logger.info(f"已删除本地图片: {image_path}")
            except Exception as e:
                logger.warning(f"删除图片文件失败: {e}")

            # 避免发送过快
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception(f"发送图片失败: {e}")
            fail_count += 1

    # 返回结果
    device_text = f"（{device}端）" if picture_type == "acg" else ""
    fourk_text = f"（{fourk_type}）" if picture_type == "random4kPic" else ""

    # 中文数字映射
    cn_nums = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    success_cn = cn_nums.get(success_count, str(success_count))
    fail_cn = cn_nums.get(fail_count, str(fail_count))

    if fail_count == 0:
        return f"✅ 已成功发送 {success_cn} 张 {TYPE_NAMES[picture_type]} 图片{device_text}{fourk_text}到 {message_type} {target_id}"
    else:
        return f"⚠️ 已发送 {success_cn} 张 {TYPE_NAMES[picture_type]} 图片{device_text}{fourk_text}，失败 {fail_cn} 张"
