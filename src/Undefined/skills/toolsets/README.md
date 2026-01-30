# Toolsets（工具集合）

Toolsets 是按功能分类组织的工具集合，用于将相关工具分组管理。

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
    ├── get_current_time/
    ├── list_schedule_tasks/
    └── update_schedule_task/
```

## 命名规范

- **目录结构**: `toolsets/{category}/{tool_name}/`
- **注册名称**: `{category}.{tool_name}`
- **示例**:
  - `toolsets/render/render_html/` → 注册为 `render.render_html`
  - `toolsets/scheduler/create_schedule_task/` → 注册为 `scheduler.create_schedule_task`

## 添加新工具

1. 在对应分类目录下创建新目录
2. 添加 `config.json`（工具定义，使用 OpenAI function calling 格式）
3. 添加 `handler.py`（执行逻辑，必须包含 `async def execute(args, context)`）
4. 自动被 `ToolRegistry` 发现和注册

## 运行特性

- **延迟加载 (Lazy Load)**：仅在首次调用时导入 `handler.py`。
- **超时与取消**：单次执行默认 120s 超时，超时会返回提示并记录统计。
- **结构化日志**：统一输出 `event=execute`、`status=success/timeout/error` 等字段。
- **热重载**：检测到 `toolsets/` 中的变更会自动重新加载。

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
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
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
- `scheduler.get_current_time`: 获取当前时间
- `scheduler.list_schedule_tasks`: 列出所有定时任务
- `scheduler.update_schedule_task`: 更新定时任务
