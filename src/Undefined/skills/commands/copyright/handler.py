from __future__ import annotations

from Undefined.services.commands.context import CommandContext


_COPYRIGHT_TEXT = """Undefined 版权信息与免责声明

风险提示与免责声明
1. 账号风控与封禁风险（含 QQ 账号）
   本项目依赖第三方协议端（如 NapCat/Lagrange.Core）接入平台服务。任何因账号风控、功能限制、临时冻结或永久封禁造成的损失，均由实际部署方自行承担。
2. 敏感信息处理风险
   请勿使用本项目主动收集、存储、导出或传播敏感信息。因使用者配置不当或违规处理数据导致的合规处罚及连带损失保留追究权力。
3. 合规义务归属
   使用者应确保其部署与运营行为符合所在地区法律法规、平台协议及群规。项目维护者不对使用者的具体行为及后果承担连带责任。

作者：Null<1708213363@qq.com>
开源链接：github.com/69gg/Undefined
PyPI 包：Undefined-bot
开源 LICENSE：MIT
"""


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /copyright。"""

    _ = args
    await context.sender.send_group_message(context.group_id, _COPYRIGHT_TEXT)
