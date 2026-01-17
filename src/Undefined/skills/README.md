# Skills Directory

技能目录，包含基础工具（tools）和工具集合（agents）。

## 目录结构

```
skills/
├── tools/          # 基础小工具，直接暴露给 AI 调用
│   ├── __init__.py
│   ├── send_message/
│   ├── send_private_message/
│   └── ...
│
└── agents/         # 工具集合，AI Agent 封装
    ├── __init__.py
    ├── code_analysis_agent/
    ├── web_agent/
    ├── social_agent/
    ├── entertainment_agent/
    └── info_agent/
```

## Tools vs Agents

### Tools（工具）
- 单一功能，直接暴露给主 AI
- 使用 OpenAI function calling 格式
- 示例：`send_message`, `get_current_time`, `analyze_multimodal`

### Agents（代理）
- 工具集合，内部可调用多个子工具
- 使用 OpenAI function calling 格式暴露
- 参数统一为 `prompt`，由 Agent 内部解析
- 支持自动发现子工具并注册
- 适用于复杂场景和领域特定任务

## 添加新工具

### 添加 Tools
1. 在 `skills/tools/` 下创建新目录
2. 添加 `config.json`（工具定义）
3. 添加 `handler.py`（执行逻辑）
4. 自动被 `ToolRegistry` 发现和注册

### 添加 Agents
1. 在 `skills/agents/` 下创建新目录
2. 添加 `intro.md`（给主 AI 看的能力说明）
3. 添加 `prompt.md`（Agent 系统提示词）
4. 添加 `config.json`（Agent 定义）
5. 添加 `handler.py`（Agent 执行逻辑）
6. 在 `tools/` 子目录中添加子工具
7. 自动被 `AgentRegistry` 发现和注册
