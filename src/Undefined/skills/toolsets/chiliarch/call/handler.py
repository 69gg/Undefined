"""所有平台业务经注入的原生渠道服务执行。"""

from typing import Any
import json


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    service = context.get("chiliarch_service")
    if service is None:
        return "chiliarch 渠道未启用"
    action = str(args.get("action", "status"))
    arguments = args.get("arguments", {})
    if not isinstance(arguments, dict):
        return "chiliarch 参数无效：arguments 必须为对象"
    try:
        result = await service.invoke(action, arguments, context)
        return json.dumps(result, ensure_ascii=False, default=str)
    except (ValueError, KeyError, TypeError) as exc:
        return f"chiliarch 参数无效：{exc}"
    except Exception as exc:
        # 不把可能包含私有状态/凭证的异常正文交给模型或日志。
        return f"chiliarch 操作未完成（{type(exc).__name__}）；先查询状态或原 request_id，避免重复副作用"
