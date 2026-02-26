from __future__ import annotations

from Undefined.services.commands.context import CommandContext


_COPYRIGHT_TEXT = """Undefined 使用说明与风险提示

免责声明
本项目基于 MIT License 开源发布，并按“原样”（AS IS）提供。
作者不对因使用、部署、修改或分发本项目而产生的任何直接或间接损失承担责任。

使用风险说明
1. 第三方平台风险
   本项目可能依赖第三方协议端或平台服务（如 NapCat / Lagrange.Core 等）。
   因平台风控、功能限制、账号冻结或封禁等造成的影响与损失，
   由实际部署与使用者自行承担。

2. 数据与隐私风险
   使用者应合理配置系统，避免违规收集、存储或传播敏感信息。
   因使用者行为导致的合规风险或法律责任，由使用者自行承担。

3. 合规义务
   使用者应确保其部署与运营行为符合所在地法律法规、
   平台服务协议及相关规则。
   作者不参与具体运营行为，亦不对使用者行为承担连带责任。

作者：Null <pylindex@qq.com>
开源地址：https://github.com/69gg/Undefined
PyPI 包：Undefined-bot
许可证：MIT License
"""


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /copyright。"""

    _ = args
    await context.sender.send_group_message(context.group_id, _COPYRIGHT_TEXT)
