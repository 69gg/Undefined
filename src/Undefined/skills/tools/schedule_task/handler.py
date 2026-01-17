from typing import Any, Dict
import uuid
import logging

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """
    执行 schedule_task 工具
    """
    cron_expression = args.get("cron_expression")
    tool_name = args.get("tool_name")
    tool_args = args.get("tool_args", {})
    
    # 参数中不再提供 task_id 和 target 信息，由内部处理
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    target_type = None
    target_id = None
    
    scheduler = context.get("scheduler")
        
    # 自动推断 target
    ai_client = context.get("ai_client")
    if target_id is None and ai_client:
        if ai_client.current_group_id:
            target_id = ai_client.current_group_id
            if not target_type:
                target_type = "group"
        elif ai_client.current_user_id:
            target_id = ai_client.current_user_id
            if not target_type:
                target_type = "private"
                
    # 默认值
    if not target_type:
        target_type = "group"
        
    success = scheduler.add_task(
        task_id=task_id,
        tool_name=tool_name,
        tool_args=tool_args,
        cron_expression=cron_expression,
        target_id=target_id,
        target_type=target_type
    )
    
    if success:
        return f"定时任务 '{task_id}' 已成功添加。\n将在 '{cron_expression}' 时间执行工具 '{tool_name}'。"
    else:
        return f"添加定时任务 '{task_id}' 失败。请检查 crontab 表达式是否正确。"
