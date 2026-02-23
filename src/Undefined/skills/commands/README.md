# 斜杠指令 (Commands)

> 👈 **[返回技能中心主页](../README.md)** | **[阅读详细斜杠指令开发指南](../../../../docs/slash-commands.md)**

这里包含 Undefined 系统所有的运行时业务斜杠命令实现。该底层引擎架构支持动态自动发现与注册。

## 目录结构
每一个具体的指令功能均表现为一个独立的文件夹。例如：

```text
commands/
├── addadmin/       # 在运行时动态添加普通管理员QQ的指令
├── bugfix/         # 一键读取群上下文帮你诊断并回复 bug 发作原因的娱乐工具
├── delfaq/         # 删除特定 ID 的常见问题解答
├── help/           # 打印基础指令集列表
├── lsadmin/        # 列出并获取当前系统的管理员和超管花名册
├── ...
└── my_cmd/         # 开发你的新指令所放置的位置
```

## 创建与接入示例

要在系统里跑通一个斜杠指令，你需要新建目录并放入 `config.json` 声明以及 `handler.py` 逻辑：

**config.json 格式：**
```json
{
    "name": "example",
    "description": "指令描述信息",
    "permission": "public",
    "rate_limit": "default",
    "show_in_help": true,
    "order": 100,
    "aliases": ["ex", "examples"]
}
```
*提示： `permission` 可选 `public` / `admin` / `superadmin`。*

**handler.py 必须实现 `execute` 方法：**
```python
import logging
from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

async def execute(args: list[str], context: CommandContext) -> None:
    # 完整的业务逻辑
    await context.sender.send_group_message(context.group_id, f"Hello World! {args}")
```

所有的改动生效且没有报错之后，机器人将能够在聊天窗口通过 `/example` 被唤醒！

更多关于上下文 `CommandContext` 注入属性的帮助可参考 [顶级使用文档](../../../../docs/slash-commands.md)。
