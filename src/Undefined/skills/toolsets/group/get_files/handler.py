import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取群文件列表"""
    ai_client = context.get("ai_client")
    group_id = args.get("group_id") or context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群文件功能不可用（OneBot 客户端未设置）"

    try:
        # 使用 _call_api 调用 get_group_root_files
        result = await onebot_client._call_api(
            "get_group_root_files", {"group_id": group_id}
        )
        data = result.get("data", {})

        files = data.get("files", [])
        folders = data.get("folders", [])

        if not files and not folders:
            return f"群 {group_id} 的根目录下没有文件或文件夹"

        result_parts = [f"【群文件列表】群号: {group_id}"]

        if folders:
            result_parts.append("\n📁 文件夹:")
            for folder in folders:
                name = folder.get("folder_name", "未知文件夹")
                creator = folder.get("creator_name", "")
                result_parts.append(f"  - {name} (创建者: {creator})")

        if files:
            result_parts.append("\n📄 文件:")
            for file in files:
                name = file.get("file_name", "未知文件")
                size = file.get("file_size", 0)
                # 转换为 MB
                size_mb = size / (1024 * 1024)
                uploader = file.get("uploader_name", "")

                # 某些实现（如 NapCat）在 get_group_root_files 中不直接提供下载 URL
                # 但提供 file_id。下载通常需要调用 get_group_file_url
                file_id = file.get("file_id")

                result_info = f"  - {name} ({size_mb:.2f} MB) [上传者: {uploader}]"

                # 尝试获取下载链接
                try:
                    url_res = await onebot_client._call_api(
                        "get_group_file_url",
                        {
                            "group_id": group_id,
                            "file_id": file_id,
                            "busid": file.get("busid", 0),
                        },
                    )
                    url = url_res.get("data", {}).get("url")
                    if url:
                        result_info += f"\n    🔗 链接: {url}"
                except Exception:
                    # 如果获取失败（如不支持该接口），则跳过
                    pass

                result_parts.append(result_info)

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(f"获取群文件失败: {e}")
        return f"获取失败：{str(e)} (可能当前 OneBot 实现不支持该接口)"
