# 技能中心 (Skills Architecture)

> 👈 **[返回项目主页](../../../../README.md)** | **[阅读详细扩展开发指南](../../../../docs/development.md)**

技能目录，包含基础工具（tools）、智能代理（agents）、工具集合（toolsets）和 Anthropic Skills（anthropic_skills）。它构成了 Undefined 机器人的所有核心能力基座。

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
│   │   ├── anthropic_skills/  # Agent 私有 Anthropic Skills（可选）
│   │   ├── tools/
│   │   ├── config.json
│   │   ├── handler.py
│   │   ├── prompt.md
│   │   └── intro.md
│   ├── file_analysis_agent/
│   ├── naga_code_analysis_agent/
│   ├── info_agent/
│   └── entertainment_agent/
│
├── toolsets/       # 工具集合，按功能分类组织
│   ├── __init__.py
│   ├── render/     # 渲染工具集
│   │   ├── render_html/
│   │   ├── render_latex/
│   │   └── render_markdown/
│   └── scheduler/  # 定时任务工具集
│       ├── create_schedule_task/
│       ├── delete_schedule_task/
│       ├── get_current_time/
│       ├── list_schedule_tasks/
│       └── update_schedule_task/
│
├── commands/       # 平台级斜杠指令，以插件形式动态加载
│   ├── __init__.py
│   ├── help/
│   ├── stats/
│   ├── addadmin/
│   └── ...
│
└── anthropic_skills/  # Anthropic Skills（SKILL.md 格式）
    ├── __init__.py
    ├── loader.py
    └── <skill-name>/
        ├── SKILL.md       # 必须：YAML frontmatter + Markdown body
        ├── references/    # 可选：参考文档
        ├── scripts/       # 可选：脚本文件
        └── assets/        # 可选：资源文件
```

## 工具、智能体、工具集与 Anthropic Skills 对比

### 基础工具

- **定位**: 单一功能的原子操作
- **调用方式**: 直接暴露给主 AI
- **Agent 可见性**: 默认仅主 AI 可见；可通过 `skills/tools/{tool_name}/callable.json` 按白名单暴露给 Agent
- **命名规则**: 简单名称（如 `send_message`, `save_memory`）
- **适用场景**: 通用、高频使用的简单操作
- **示例**: `send_message`, `get_recent_messages`, `save_memory`, `end`

### 工具集

- **定位**: 按功能分类的相关工具组
- **调用方式**: 直接暴露给主 AI
- **Agent 可见性**: 默认仅主 AI 可见；可通过 `skills/toolsets/{category}/{tool_name}/callable.json` 按白名单暴露给 Agent
- **命名规则**: `{category}.{tool_name}`（如 `render.render_html`, `scheduler.create_schedule_task`）
- **目录结构**: `toolsets/{category}/{tool_name}/`
- **适用场景**: 功能相关、需要分组管理的工具
- **示例**: `render.render_html`, `scheduler.create_schedule_task`, `render.render_markdown`

### 智能体

- **定位**: 封装复杂任务的 AI Agent
- **调用方式**: 暴露给主 AI，内部可调用多个子工具
- **命名规则**: Agent 名称（如 `web_agent`, `file_analysis_agent`）
- **参数**: 统一使用 `prompt` 参数，由 Agent 内部解析
- **适用场景**: 复杂场景、领域特定任务、需要多步推理
- **特性**: 支持自动发现子工具并注册
- **示例**: `web_agent`, `file_analysis_agent`, `naga_code_analysis_agent`

### Anthropic Skills

- **定位**: 领域知识/指令注入，遵循 [agentskills.io](https://agentskills.io) 开放标准
- **调用方式**: 注册为 `skills-_-<name>` function tool，AI 调用后返回完整指令内容
- **命名规则**: 内部 `skills.<name>`，注册为 `skills-_-<name>`（使用 `config.tools_dot_delimiter`）
- **目录结构**: `anthropic_skills/<skill-name>/SKILL.md` 或 `agents/<agent>/anthropic_skills/<skill-name>/`
- **适用场景**: 提供领域专业知识、工作流程指导、最佳实践
- **特性**: 渐进式披露（元数据始终注入，完整内容按需获取）、热重载
- **示例**: `pdf-processing`, `code-review`, `data-analysis`

## 运行机制（重要）

- **延迟加载**: 仅在首次执行时才导入 `handler.py`，加快启动速度。
- **结构化日志 + 统计**: 统一输出 `event=execute`、`status=success/timeout/error` 等结构化字段，并记录执行耗时与成功/失败计数。
- **超时与取消**: 所有技能执行默认 120 秒超时，超时会返回提示并记录统计。
- **热重载**: 自动扫描 `skills/` 目录，检测到 `config.json` 或 `handler.py` 变更后自动重载。

## 选择指南

| 特性 | 基础工具 | 工具集 | 智能体 | 平台指令 (Commands) | Anthropic Skills |
|------|----------|--------|--------|------------------|------------------|
| 复杂度 | 低 | 中 | 高 | 中（独立执行逻辑） | 低（纯提示词） |
| 调用层级 | 直接调用 | 直接调用 | 间接调用 | 被群聊拦截器直接执行 | 直接调用（tool） |
| 内部工具 | 无 | 无 | 可包含多个子工具 | 无 | 无（知识注入） |
| 适用场景 | 通用原子操作 | 功能分组工具 | 领域复杂任务 | 基础系统管理与控制 | 领域知识/指导 |
| 格式 | config.json + handler.py | config.json + handler.py | config.json + handler.py + prompt.md | config.json + handler.py | SKILL.md |

## 添加新技能

### 添加基础工具

1. 在 `skills/tools/` 下创建新目录
2. 添加 `config.json`（工具定义，OpenAI 函数调用格式）
3. 添加 `handler.py`（执行逻辑，必须包含 `async def execute(args, context)`）
4. 自动被 `ToolRegistry` 发现和注册

### 添加工具集

1. 在 `skills/toolsets/` 下创建分类目录（如 `my_category/`）
2. 在分类目录下创建工具目录（如 `my_tool/`）
3. 添加 `config.json`（工具定义）
4. 添加 `handler.py`（执行逻辑）
5. 自动被 `ToolRegistry` 发现和注册，名称为 `my_category.my_tool`
6. （可选）添加 `callable.json` 将该工具按白名单暴露给 Agent

详细说明请参考 [toolsets/README.md](./toolsets/README.md)

### 添加智能体

1. 在 `skills/agents/` 下创建新目录
2. 添加 `intro.md`（给主 AI 看的能力说明）
3. （可选）生成 `intro.generated.md`（自动补充说明，系统启动时可自动生成）
4. 添加 `prompt.md`（智能体系统提示词）
5. 添加 `config.json`（Agent 定义）
6. 添加 `handler.py`（Agent 执行逻辑）
7. 在 `tools/` 子目录中添加子工具（可选）
8. 自动被 `AgentRegistry` 发现和注册

### 添加 Anthropic Skills

**全局 Skills（所有 AI 可用）：**

1. 在 `skills/anthropic_skills/` 下创建新目录（如 `pdf-processing/`）
2. 添加 `SKILL.md` 文件，包含 YAML frontmatter 和 Markdown 正文
3. 目录名应与 `name` 字段一致
4. 自动被 `AnthropicSkillRegistry` 发现并注册为 `skills-_-<name>` 工具

**Agent 私有 Skills（仅该 Agent 可用）：**

1. 在 `skills/agents/<agent_name>/anthropic_skills/` 下创建 skill 目录
2. 添加 `SKILL.md` 文件
3. Agent 执行时自动发现并加载，工具仅对该 Agent 可见

### 添加平台斜杠指令 (Commands)

详细说明请参考 [顶级斜杠指令指南](../../../../docs/slash-commands.md)。
1. 在 `skills/commands/` 下创建新目录
2. 添加 `config.json`（设定命令的前缀、优先级和权限限定）
3. 添加 `handler.py`（执行逻辑，接收和回复用户的直接指令）
4. 自动被 `CommandRegistry` 发现和注册

**SKILL.md 格式示例：**

```yaml
---
name: pdf-processing
description: 从 PDF 文件中提取文本和表格，填写表单。当用户提到 PDF、表单或文档提取时使用。
---

# PDF 处理指南

## 文本提取

使用 pdfplumber:

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```

## 表格提取

```python
tables = pdf.pages[0].extract_tables()
```

## 最佳实践

1. 处理大文件时使用分页加载
2. 表格提取前检查是否有表格
3. 中文 PDF 可能需要指定编码
```

**规范要求：**

| 字段 | 必填 | 约束 |
|------|------|------|
| `name` | 是 | 小写字母/数字/连字符，最大64字符，不能以连字符开头/结尾 |
| `description` | 是 | 最大1024字符，应说明**做什么**和**何时使用** |
| Markdown 正文 | 否 | 详细指令/知识内容，建议 < 5000 字符 |

## 最佳实践与移植指南

为了确保技能目录 (`skills/`) 的可移植性（例如直接移动到其他项目中使用），请遵循以下准则：

1.  **避免外部依赖**:
    -   尽量不要在 `handler.py` 中引用 `skills/` 目录之外的本地模块（如 `from Undefined.xxx import`）。
    -   如果是通用库（如 `httpx`, `pillow`），直接引用即可。

2.  **使用 RequestContext 获取请求信息**（推荐）:
    -   使用 `RequestContext` 获取当前请求的 group_id、user_id 等信息，无需手动传递参数。
    -   这是获取请求上下文的首选方式，支持并发隔离。

    ```python
    from Undefined.context import get_group_id, get_user_id, get_request_id
    
    async def execute(args, context):
        # 优先从 args 获取（用户显式指定）
        group_id = args.get("group_id") or get_group_id()
        user_id = args.get("user_id") or get_user_id()
        request_id = get_request_id()  # 自动UUID追踪
        
        if not group_id:
            return "无法确定群ID"
        
        # 使用 group_id 进行操作...
    ```

3.  **使用 Context 注入外部依赖**:
    -   如果需要使用外部项目的功能（如数据库连接、特殊的渲染函数），通过 `context` 参数传入。
-   主程序（`handlers.py` 或 `ai/` 运行时）负责在调用时将这些依赖放入 `context`。

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

4.  **向后兼容的获取方式**（仅在必要时使用）:
    -   如果 `RequestContext` 不可用，可以回退到从 `context` 获取：
    
    ```python
    from Undefined.context import get_group_id
    
    async def execute(args, context):
        # 优先级：args > RequestContext > context > ai_client（已废弃）
        group_id = args.get("group_id") or get_group_id() or context.get("group_id")
    ```

5.  **统一的加载机制**:
    -   所有工具和 Agent 均通过统一加载器自动加载（支持延迟加载与热重载）。
    -   保持目录结构（`config.json` + `handler.py`）的一致性。

6.  **异步安全 I/O**:
-   避免在 `handler.py` 中进行阻塞式磁盘 I/O（大量 `open()` / 读写大文件 / 频繁 flush）。如必须使用同步 I/O，请用 `asyncio.to_thread` 移出事件循环。
-   不要引入平台专用锁实现（如 `fcntl`）；在本仓库内读写 JSON/行追加请优先复用 `src/Undefined/utils/io.py`（跨平台锁 + 原子写入）。
