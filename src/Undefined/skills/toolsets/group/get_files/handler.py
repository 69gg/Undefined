import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _format_folders(folders: list[Dict[str, Any]]) -> list[str]:
    """格式化文件夹列表"""
    lines: list[str] = []
    if folders:
        lines.append("\n📁 文件夹:")
        for folder in folders:
            name = folder.get("folder_name", "未知文件夹")
            creator = folder.get("creator_name", "")
            folder_id = folder.get("folder_id", "")
            lines.append(f"  - {name} (创建者: {creator}, folder_id: {folder_id})")
    return lines


async def _format_files(
    files: list[Dict[str, Any]],
    group_id: int,
    onebot_client: Any,
) -> list[str]:
    """格式化文件列表，并尝试获取下载链接"""
    lines: list[str] = []
    if files:
        lines.append("\n📄 文件:")
        for file in files:
            name = file.get("file_name", "未知文件")
            size = file.get("file_size", 0)
            size_mb = size / (1024 * 1024)
            uploader = file.get("uploader_name", "")
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
                pass

            lines.append(result_info)
    return lines


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """获取群文件列表"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群文件功能不可用（OneBot 客户端未设置）"

    folder_id: str | None = args.get("folder_id")

    try:
        if folder_id:
            # 查看指定文件夹内的文件
            result = await onebot_client._call_api(
                "get_group_files_by_folder",
                {"group_id": group_id, "folder_id": folder_id},
            )
            location = f"文件夹 {folder_id}"
        else:
            # 查看根目录
            result = await onebot_client._call_api(
                "get_group_root_files", {"group_id": group_id}
            )
            location = "根目录"

        data = result.get("data", {})
        files: list[Dict[str, Any]] = data.get("files", [])
        folders: list[Dict[str, Any]] = data.get("folders", [])

        if not files and not folders:
            return f"群 {group_id} 的{location}下没有文件或文件夹"

        result_parts = [f"【群文件列表】群号: {group_id} | 位置: {location}"]
        result_parts.extend(_format_folders(folders))
        result_parts.extend(await _format_files(files, group_id, onebot_client))

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(
            "获取群文件失败: group=%s folder=%s request_id=%s err=%s",
            group_id,
            folder_id,
            request_id,
            e,
        )
        return "获取失败：群文件服务暂时不可用，或当前 OneBot 实现不支持该接口"
