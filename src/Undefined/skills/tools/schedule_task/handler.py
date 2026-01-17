from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 schedule_task 工具
    [已废弃] 此工具已废弃，请使用 scheduler_agent 代替。
    scheduler_agent 提供更完整的功能：创建、删除、修改、查看定时任务，支持执行次数限制。
    """
    return """❌ **此工具已废弃**

请使用 **scheduler_agent** 代替，scheduler_agent 提供更完整的定时任务管理功能：

1. **创建定时任务** - 支持任务名称、执行次数限制
2. **删除定时任务** - 可以删除指定的定时任务
3. **修改定时任务** - 可以修改 crontab、工具、参数等
4. **查看任务列表** - 列出所有定时任务及其状态

使用方式：
- 调用 scheduler_agent，说明你的需求即可
- 例如："创建一个每天早上8点执行的任务"、"删除所有任务"等"""
