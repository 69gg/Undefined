# 基础工具 (Basic Tools)

本项目采用模块化工具架构，所有基础工具都位于 `src/Undefined/skills/tools/` 目录下。每个工具都是一个独立的文件夹，包含配置和实现逻辑。

## 目录结构

```text
skills/tools/
├── __init__.py          # 工具注册表
├── README.md            # 本说明文件
└── tool_name/           # 工具名称
    ├── config.json      # 工具定义 (OpenAI 格式)
    └── handler.py       # 工具逻辑实现
```

## 如何添加一个新工具

### 1. 创建工具目录
在 `src/Undefined/skills/tools/` 下创建一个新文件夹，例如 `my_new_tool`。

### 2. 编写 `config.json`
该文件定义了工具的名称、描述和参数结构（遵循 OpenAI function calling 格式）。

```json
{
    "type": "function",
    "function": {
        "name": "my_new_tool",
        "description": "这里写工具的功能描述",
        "parameters": {
            "type": "object",
            "properties": {
                "arg1": {
                    "type": "string",
                    "description": "参数1的描述"
                }
            },
            "required": ["arg1"]
        }
    }
}
```

### 3. 编写 `handler.py`
实现工具的具体逻辑。必须包含一个异步函数 `execute(args, context)`。

```python
from typing import Any, Dict

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    # 1. 获取参数
    val = args.get("arg1")
    
    # 2. 执行逻辑
    result = f"处理结果: {val}"
    
    # 3. 返回字符串结果给 AI
    return result
```

## 关于 Context 对象

`context` 参数包含了机器人运行时的上下文和回调函数，常用的有：

| 键名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `sender` | `MessageSender` | **推荐**：统一消息发送接口（自动记录历史） |
| `history_manager` | `MessageHistoryManager` | 统一历史记录管理器 |
| `send_message_callback` | `Callable` | 发送群消息的回调 (建议使用 sender) |
| `send_private_message_callback` | `Callable` | 发送私聊消息的回调 (建议使用 sender) |
| `send_image_callback` | `Callable` | 发送图片的回调 |
| `get_recent_messages_callback` | `Callable` | 获取历史消息的回调 (建议使用 history_manager) |
| `memory_storage` | `MemoryStorage` | 记忆存储实例 |
| `ai_client` | `AIClient` | AI 客户端实例（用于调用图片描述等） |
| `base_path` | `Path` | 默认的基础路径 (通常锁定在 `code/NagaAgent`) |

## 自动发现

工具注册表 (`ToolRegistry`) 会在初始化时自动扫描目录下的所有文件夹。只要文件夹内同时存在 `config.json` 和 `handler.py`，工具就会被自动加载并提供给 AI 使用，**无需手动修改任何导入代码**。

## 运行特性

- **延迟加载 (Lazy Load)**：`handler.py` 仅在首次调用时导入，减少启动耗时。
- **超时与取消**：单次执行默认 120s 超时；超时会返回提示并记录统计。
- **结构化日志**：统一输出 `event=execute`、`status=success/timeout/error` 等字段，便于检索与统计。
- **热重载**：检测到工具变更会自动重新加载（默认开启）。

可通过环境变量控制热重载：

- `SKILLS_HOT_RELOAD`：`true/false`，默认 `true`
- `SKILLS_HOT_RELOAD_INTERVAL`：扫描间隔，默认 `2.0` 秒
- `SKILLS_HOT_RELOAD_DEBOUNCE`：去抖时间，默认 `0.5` 秒

## 开发建议

1. **返回字符串**：工具的返回值必须是字符串。如果是复杂数据，请将其转为 JSON 字符串或格式化的文本。
2. **错误处理**：在 `handler.py` 中使用 `try...except` 捕获异常并返回友好的错误信息，这样 AI 可以理解发生了什么并尝试修复。
3. **安全限制**：如果涉及文件操作，务必校验路径是否在 `base_path` 范围内，防止路径穿越攻击。
