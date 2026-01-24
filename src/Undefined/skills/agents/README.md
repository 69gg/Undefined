# Agent 目录 (Agents Directory)

AI Agent 目录，每个 Agent 是一个工具集合。

## Agent 结构

每个 Agent 是一个目录，包含：

```
agent_name/
├── intro.md          # 给主 AI 看的能力说明
├── prompt.md         # Agent 系统提示词（从文件加载）
├── config.json       # Agent 定义（OpenAI function calling 格式）
├── handler.py        # Agent 执行逻辑
└── tools/            # Agent 专属子工具目录
    ├── tool1/
    ├── tool2/
    └── __init__.py
```

## 模型配置

Agent 使用独立的模型配置，通过环境变量设置：

```env
# Agent 模型配置 (用于执行 agents)
AGENT_MODEL_API_URL=          # API 地址
AGENT_MODEL_API_KEY=          # API 密钥
AGENT_MODEL_NAME=             # 模型名称
AGENT_MODEL_MAX_TOKENS=4096   # 最大 token 数
AGENT_MODEL_THINKING_ENABLED=false     # 是否启用 thinking（思维链）
AGENT_MODEL_THINKING_BUDGET_TOKENS=0    # thinking budget tokens
```

### 配置说明

| 环境变量 | 说明 | 默认值 |
|---------|------|-------|
| `AGENT_MODEL_API_URL` | Agent 模型 API 地址 | 无（必填） |
| `AGENT_MODEL_API_KEY` | Agent 模型 API 密钥 | 无（必填） |
| `AGENT_MODEL_NAME` | Agent 模型名称 | 无（必填） |
| `AGENT_MODEL_MAX_TOKENS` | 单次响应最大 token 数 | 4096 |
| `AGENT_MODEL_THINKING_ENABLED` | 是否启用思维链 | false |
| `AGENT_MODEL_THINKING_BUDGET_TOKENS` | 思维链预算 token 数量 | 0 |

## 核心文件说明

### intro.md
给主 AI 参考的 Agent 能力说明，包括：
- Agent 的功能概述
- 支持的能力列表
- 使用方式和参数说明
- 返回格式

**这是主 AI 看到的核心描述**，系统会自动将 `intro.md` 的内容作为 Agent 的 description 传递给 AI。

示例：
```markdown
# XXX 助手

## 能力
- 功能1
- 功能2

## 使用方式
- 提供 xxx 参数
```

### prompt.md
Agent 内部的系统提示词，**从文件加载**，指导 Agent 如何选择和使用工具。

文件位置：`skills/agents/{agent_name}/prompt.md`

示例：
```markdown
你是一个 XXX 助手...

## 你的任务
1. 理解用户需求
2. 选择合适的工具
3. 返回结果
```

### config.json
Agent 的 OpenAI function calling 定义。

**注意**：description 字段可选，不建议手动填写。系统会自动从 `intro.md` 读取内容作为 description 传递给 AI。

现有配置中的 description 仅用于向后兼容，未来将逐步移除。

```json
{
    "type": "function",
    "function": {
        "name": "agent_name",
        "description": "Agent 描述（无需填写，将自动从 intro.md 覆盖）",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "用户需求描述"
                }
            },
            "required": ["prompt"]
        }
    }
}
```

### handler.py
Agent 的执行逻辑，负责：
1. 从 `prompt.md` 加载系统提示词
2. 使用 `AGENT_MODEL_*` 配置调用模型
3. 通过 `AgentToolRegistry` 调用子工具
4. 返回结果给主 AI

## 添加新 Agent

### 1. 创建 Agent 目录
```bash
mkdir -p skills/agents/my_agent/tools
```

### 2. 创建必要文件
- `intro.md` - Agent 能力说明
- `prompt.md` - Agent 系统提示词
- `config.json` - Agent 定义
- `handler.py` - Agent 执行逻辑

### 3. 添加子工具
将工具目录移动到 `tools/` 下：
```bash
mv skills/tools/my_tool skills/agents/my_agent/tools/
```
或添加工具。

### 4. 自动发现
重启后 `AgentRegistry` 会自动发现并加载新 Agent。

## 自动发现

`AgentRegistry` 会自动发现 `skills/agents/` 下的所有 Agent 并加载。
每个 Agent 内部的子工具由 `AgentToolRegistry` 自动发现。

## 现有 Agents

### web_agent（网络搜索助手）
- **功能**：网页搜索和网页内容获取
- **适用场景**：获取互联网最新信息、搜索新闻、爬取网页内容
- **子工具**：`search_web`, `fetch_web`

### file_analysis_agent（文件分析助手）
- **功能**：分析代码、PDF、Docx、Xlsx 等多种格式文件
- **适用场景**：代码分析、文档解析、文件内容提取
- **子工具**：`read_file`, `analyze_code`, `analyze_pdf`, `analyze_docx`, `analyze_xlsx`

### naga_code_analysis_agent（NagaAgent 代码分析助手）
- **功能**：专门用于分析 NagaAgent 框架及当前项目的源码
- **适用场景**：深入分析 NagaAgent 架构、项目代码审查
- **子工具**：`read_file`, `search_code`, `analyze_structure`

### info_agent（信息查询助手）
- **功能**：查询天气、热搜、快递、WHOIS 等信息
- **适用场景**：天气查询、热点新闻、快递追踪、域名查询
- **子工具**：`get_weather`, `get_hot_search`, `query_express`, `whois_query`

### social_agent（社交娱乐助手）
- **功能**：B 站搜索、音乐搜索及点歌
- **适用场景**：搜索 B 站视频、音乐搜索、点歌服务
- **子工具**：`search_bilibili`, `search_music`, `play_music`

### entertainment_agent（娱乐助手）
- **功能**：运势查询、笑话、占卜等娱乐功能
- **适用场景**：查看运势、获取娱乐内容
- **子工具**：`get_horoscope`, `get_joke`, `fortune_telling`
