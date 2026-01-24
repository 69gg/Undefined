# 技能目录 (Skills Directory)

技能目录，包含基础工具（tools）、智能代理（agents）和工具集合（toolsets）。

## 目录结构

```
skills/
├── tools/          # 基础小工具，直接暴露给 AI 调用
│   ├── __init__.py
│   ├── send_message/
│   ├── get_recent_messages/
│   ├── save_memory/
│   └── ...
│
├── agents/         # 智能代理，封装复杂任务的 AI Agent
│   ├── __init__.py
│   ├── web_agent/
│   ├── file_analysis_agent/
│   ├── naga_code_analysis_agent/
│   ├── info_agent/
│   ├── social_agent/
│   └── entertainment_agent/
│
└── toolsets/       # 工具集合，按功能分类组织
    ├── __init__.py
    ├── render/     # 渲染工具集
    │   ├── render_html/
    │   ├── render_latex/
    │   └── render_markdown/
    └── scheduler/  # 定时任务工具集
        ├── create_schedule_task/
        ├── delete_schedule_task/
        ├── get_current_time/
        ├── list_schedule_tasks/
        └── update_schedule_task/
```

## Tools vs Agents vs Toolsets

### Tools（基础工具）

- **定位**: 单一功能的原子操作
- **调用方式**: 直接暴露给主 AI
- **命名规则**: 简单名称（如 `send_message`, `save_memory`）
- **适用场景**: 通用、高频使用的简单操作
- **示例**: `send_message`, `get_recent_messages`, `save_memory`, `end`

### Toolsets（工具集合）

- **定位**: 按功能分类的相关工具组
- **调用方式**: 直接暴露给主 AI
- **命名规则**: `{category}.{tool_name}`（如 `render.render_html`, `scheduler.create_schedule_task`）
- **目录结构**: `toolsets/{category}/{tool_name}/`
- **适用场景**: 功能相关、需要分组管理的工具
- **示例**: `render.render_html`, `scheduler.create_schedule_task`, `render.render_markdown`

### Agents（智能代理）

- **定位**: 封装复杂任务的 AI Agent
- **调用方式**: 暴露给主 AI，内部可调用多个子工具
- **命名规则**: Agent 名称（如 `web_agent`, `file_analysis_agent`）
- **参数**: 统一使用 `prompt` 参数，由 Agent 内部解析
- **适用场景**: 复杂场景、领域特定任务、需要多步推理
- **特性**: 支持自动发现子工具并注册
- **示例**: `web_agent`, `file_analysis_agent`, `naga_code_analysis_agent`

## 选择指南

| 特性 | Tools | Toolsets | Agents |
|------|-------|----------|--------|
| 复杂度 | 低 | 中 | 高 |
| 调用层级 | 直接调用 | 直接调用 | 间接调用（通过 prompt） |
| 内部工具 | 无 | 无 | 可包含多个子工具 |
| 适用场景 | 通用原子操作 | 功能分组工具 | 领域复杂任务 |

## 添加新技能

### 添加 Tools

1. 在 `skills/tools/` 下创建新目录
2. 添加 `config.json`（工具定义，OpenAI function calling 格式）
3. 添加 `handler.py`（执行逻辑，必须包含 `async def execute(args, context)`）
4. 自动被 `ToolRegistry` 发现和注册

### 添加 Toolsets

1. 在 `skills/toolsets/` 下创建分类目录（如 `my_category/`）
2. 在分类目录下创建工具目录（如 `my_tool/`）
3. 添加 `config.json`（工具定义）
4. 添加 `handler.py`（执行逻辑）
5. 自动被 `ToolRegistry` 发现和注册，名称为 `my_category.my_tool`

详细说明请参考 [toolsets/README.md](./toolsets/README.md)

### 添加 Agents

1. 在 `skills/agents/` 下创建新目录
2. 添加 `intro.md`（给主 AI 看的能力说明）
3. 添加 `prompt.md`（Agent 系统提示词）
4. 添加 `config.json`（Agent 定义）
5. 添加 `handler.py`（Agent 执行逻辑）
6. 在 `tools/` 子目录中添加子工具（可选）
7. 自动被 `AgentRegistry` 发现和注册

## 最佳实践与移植指南

为了确保技能目录 (`skills/`) 的可移植性（例如直接移动到其他项目中使用），请遵循以下准则：

1.  **避免外部依赖**:
    -   尽量不要在 `handler.py` 中引用 `skills/` 目录之外的本地模块（如 `from Undefined.xxx import`）。
    -   如果是通用库（如 `httpx`, `pillow`），直接引用即可。

2.  **使用 Context 注入依赖**:
    -   如果你需要使用外部项目的功能（如数据库连接、特殊的渲染函数），请通过 `execute` 函数的 `context` 参数传入。
    -   主程序（`handlers.py` 或 `ai.py`）负责在调用 `execute_tool` 时将这些依赖放入 `context` 或 `extra_context`。

    ```python
    # 错误的做法
    from MyProject.utils import heavy_function

    async def execute(args, context):
        await heavy_function()

    # 正确的做法
    async def execute(args, context):
        heavy_func = context.get("heavy_function")
        if not heavy_func:
            return "依赖未注入"
        await heavy_func()
    ```

3.  **统一的加载机制**:
    -   所有工具和 Agent 均通过继承 `BaseRegistry` 的加载器自动加载。
    -   保持目录结构（`config.json` + `handler.py`）的一致性。
