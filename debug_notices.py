import asyncio
import json
import os
import sys

# 将 src 目录添加到路径
sys.path.append(os.path.abspath("src"))

try:
    from Undefined.config import get_config
    from Undefined.onebot import OneBotClient
except ImportError as e:
    print(f"Error: 无法导入项目模块。请确保在项目根目录下运行。({e})")
    sys.exit(1)


async def debug_notices(group_id: int) -> None:
    print("--- 正在加载配置 ---")
    try:
        config = get_config()
        ws_url = config.onebot_ws_url
        token = config.onebot_token
        print(f"WS URL: {ws_url}")
        if token:
            print("Token: [已设置]")
        else:
            print("Token: [未设置]")
    except Exception as e:
        print(f"加载配置失败: {e}")
        return

    print(f"\n--- 正在连接并调用 _get_group_notice (Group: {group_id}) ---")
    client = OneBotClient(ws_url, token)
    try:
        await client.connect()
        # 启动接收循环任务以便接收 API 响应
        asyncio.create_task(client.run())

        # 直接调用 _call_api 捕获原始响应
        raw_result = await client._call_api("_get_group_notice", {"group_id": group_id})

        print("\n=== API 原始响应 (Raw JSON) ===")
        print(json.dumps(raw_result, indent=2, ensure_ascii=False))
        print("==============================\n")

        # 结果分析
        status = raw_result.get("status")
        retcode = raw_result.get("retcode")
        data = raw_result.get("data")

        print(f"Status: {status}")
        print(f"Retcode: {retcode}")

        if data is None:
            print("警告: 响应中的 data 字段为空。")
        else:
            print(f"Data 类型: {type(data)}")
            if isinstance(data, dict):
                print(f"Data 键值: {list(data.keys())}")
            elif isinstance(data, list):
                print(f"Data 长度: {len(data)}")
                if data:
                    print(f"首条数据键值: {list(data[0].keys())}")

    except Exception as e:
        print(f"\n执行过程中发生错误: {e}")
    finally:
        client.stop()
        await client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            gid = int(sys.argv[1])
            asyncio.run(debug_notices(gid))
        except ValueError:
            print("错误: 群号必须是数字。")
    else:
        print("使用方法: python3 debug_notices.py <群号>")
