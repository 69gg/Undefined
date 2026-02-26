# 工具集 (Toolsets)

> 👈 **[返回技能中心主页](../README.md)** | **[阅读详细扩展开发指南](../../../../../docs/development.md)**

工具集用于按功能分类组织互相有关联的工具，便于分组管理与统一结构化命名。

## 目录结构

```
toolsets/
├── render/                  # 渲染工具集
│   ├── render_html/         # HTML 渲染
│   ├── render_latex/        # LaTeX 渲染
│   └── render_markdown/     # Markdown 渲染
└── scheduler/               # 定时任务工具集
    ├── create_schedule_task/
    ├── delete_schedule_task/
    ├── list_schedule_tasks/
    └── update_schedule_task/
```

## 命名规范

- **目录结构**: `toolsets/{category}/{tool_name}/`
- **注册名称**: `{category}.{tool_name}`
- **示例**:
  - `toolsets/render/render_html/` → 注册为 `render.render_html`
  - `toolsets/scheduler/create_schedule_task/` → 注册为 `scheduler.create_schedule_task`

## 暴露给 Agent（callable.json）

默认情况下，工具集工具仅主 AI 可见。可通过 `callable.json` 按白名单暴露给 Agent：

**单个工具**（放在工具目录下）：

```
toolsets/{category}/{tool_name}/callable.json
```

**整个分类**（放在分类目录下，上级覆盖下级）：

```
toolsets/{category}/callable.json
```

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

注册名为 `{category}.{tool_name}`。分类级与工具级同时存在时，分类级优先。详见 [docs/callable.md](../../../../docs/callable.md)。

## 添加新工具

1. 在对应分类目录下创建新目录
2. 添加 `config.json`（工具定义，使用 OpenAI 函数调用格式）
3. 添加 `handler.py`（执行逻辑，必须包含 `async def execute(args, context)`）
4. 自动被 `ToolRegistry` 发现和注册

## 运行特性

- **延迟加载**：仅在首次调用时导入 `handler.py`。
- **超时与取消**：单次执行默认 120 秒超时，超时会返回提示并记录统计。
- **结构化日志**：统一输出 `event=execute`、`status=success/timeout/error` 等字段。
- **热重载**：检测到 `toolsets/` 中的变更会自动重新加载。

热重载参数可通过 `config.toml` 的 `[skills]` 段配置；也支持同名环境变量覆盖。

## 示例：添加一个新工具

### 1. 创建目录

```bash
mkdir -p toolsets/my_category/my_new_tool
```

### 2. 创建 config.json

```json
{
    "type": "function",
    "function": {
        "name": "my_new_tool",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "参数描述"
                }
            },
            "required": ["param1"]
        }
    }
}
```

### 3. 创建 handler.py

```python
from typing import Any
import logging

logger = logging.getLogger(__name__)

async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行工具逻辑"""
    param1 = args.get("param1")

    # 获取上下文中的回调函数
    send_message_callback = context.get("send_message_callback")

    # 执行你的逻辑
    result = f"处理结果: {param1}"

    return result
```

## 上下文参数

`context` 字典包含以下可用参数：

- `send_message_callback`: 发送消息的回调函数
- `send_image_callback`: 发送图片的回调函数
- `db`: 数据库连接
- 其他自定义上下文

## 现有工具集

### Render（渲染）

- `render.render_html`: 将 HTML 渲染为图片
- `render.render_latex`: 将 LaTeX 渲染为图片
- `render.render_markdown`: 将 Markdown 渲染为图片

### Scheduler（定时任务）

- `scheduler.create_schedule_task`: 创建定时任务
- `scheduler.delete_schedule_task`: 删除定时任务
- `scheduler.list_schedule_tasks`: 列出所有定时任务
- `scheduler.update_schedule_task`: 更新定时任务
- `scheduler.create_schedule_task` / `scheduler.update_schedule_task` 支持 `self_instruction` 参数，可在未来时刻调用 AI 自己执行一条延迟指令
