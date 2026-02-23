# 智能体目录 (Agents)

> 👈 **[返回技能中心主页](../README.md)** | **[阅读详细扩展开发指南](../../../../../docs/development.md)**

智能体目录，每个智能体都是一个由大模型驱动的高度自治的复杂任务处理器，它可以自行思考并反复调用下发给它的原子工具（tools）以达成最终目的。

## 智能体结构

每个智能体是一个目录，包含：

```
agent_name/
├── intro.md          # 给主 AI 看的能力说明
├── intro.generated.md# 自动生成的补充说明（可选）
├── prompt.md         # 智能体系统提示词（从文件加载）
├── config.json       # 智能体定义（OpenAI 函数调用格式）
├── handler.py        # 智能体执行逻辑
└── tools/            # 智能体专属子工具目录
    ├── tool1/
    ├── tool2/
    └── __init__.py
```

## 模型配置

智能体默认使用 `config.toml` 中的 `[models.agent]` 配置；同名环境变量仍可作为兼容覆盖（用于临时调试或无文件配置场景）。

推荐在 `config.toml` 配置：

```toml
[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "..."
model = "gpt-4o-mini"
max_tokens = 4096
thinking_enabled = false
thinking_budget_tokens = 0
```

兼容的环境变量（会覆盖 `config.toml`）：

```env
AGENT_MODEL_API_URL=
AGENT_MODEL_API_KEY=
AGENT_MODEL_NAME=
AGENT_MODEL_MAX_TOKENS=4096
AGENT_MODEL_THINKING_ENABLED=false
AGENT_MODEL_THINKING_BUDGET_TOKENS=0
```

## 介绍自动生成（推荐）

启动时会对智能体代码做哈希，如果检测到变更，则将补充说明写入 `intro.generated.md`。该文件会在加载时与 `intro.md` 合并。

提示词文件位置：`res/prompts/agent_self_intro.txt`（已随 wheel 打包；运行时支持从包内读取，并可通过本地同路径文件覆盖）。

推荐在 `config.toml` 配置：

```toml
[skills]
intro_autogen_enabled = true
intro_autogen_queue_interval = 1.0
intro_autogen_max_tokens = 700
intro_hash_path = ".cache/agent_intro_hashes.json"
```

兼容的环境变量（会覆盖 `config.toml`）：

```env
AGENT_INTRO_AUTOGEN_ENABLED=true
AGENT_INTRO_AUTOGEN_QUEUE_INTERVAL=1.0
AGENT_INTRO_AUTOGEN_MAX_TOKENS=700
AGENT_INTRO_HASH_PATH=.cache/agent_intro_hashes.json
```

| 配置项（config.toml / env） | 说明 | 默认值 |
|---------|------|-------|
| `skills.intro_autogen_enabled` / `AGENT_INTRO_AUTOGEN_ENABLED` | 是否启动自动生成 | true |
| `skills.intro_autogen_queue_interval` / `AGENT_INTRO_AUTOGEN_QUEUE_INTERVAL` | 队列发车间隔（秒） | 1.0 |
| `skills.intro_autogen_max_tokens` / `AGENT_INTRO_AUTOGEN_MAX_TOKENS` | 生成最大 token | 700 |
| `skills.intro_hash_path` / `AGENT_INTRO_HASH_PATH` | hash 缓存路径 | .cache/agent_intro_hashes.json |

## 核心文件说明

### intro.md
给主 AI 参考的 Agent 能力说明，包括：
- Agent 的功能概述
- 支持的能力列表
- 边界与适用范围
- 输入偏好与注意事项

**这是主 AI 看到的核心描述**，系统会自动将 `intro.md` 与 `intro.generated.md` 的内容合并后作为 Agent 的 description 传递给 AI。

示例：
```markdown
# XXX 助手

## 定位
一句话概述

## 擅长
- 能力1
- 能力2

## 边界
- 不适用场景
```

### intro.generated.md
自动生成的补充说明文件，**不要手动编辑**。系统会在启动时检测代码变更并自动覆盖该文件。

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

**注意**：description 字段可选，不建议手动填写。系统会自动从 `intro.md` + `intro.generated.md` 读取内容作为 description 传递给 AI。

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
2. 使用 `config.toml` 的 `[models.agent]` 配置调用模型（或 `AGENT_MODEL_*` 兼容覆盖）
3. 通过 `AgentToolRegistry` 调用子工具
4. 返回结果给主 AI

## 运行特性

- **延迟加载 (Lazy Load)**：Agent `handler.py` 首次调用时导入，减少启动耗时。
- **超时与取消**：Agent 调用默认 120s 超时，超时返回提示并记录统计。
- **结构化日志**：统一输出 `event=execute`、`status=success/timeout/error` 等字段。
- **热重载**：检测到 `skills/agents/` 变更后自动重载 Agent 注册表。

## 最佳实践：统一请求与上下文

为了简化 Agent 开发并确保 Token 统计一致性，建议所有 Agent 均遵循以下最佳实践：

### 1. 使用 `ai_client.request_model`
不要直接使用 `httpx` 调用 API，而是使用 `context` 中提供的 `ai_client.request_model`。它会自动：
- 记录 Token 使用情况到系统统计中。
- 处理重试和错误抛出。
- 控制请求格式。

### 2. 实现临时对话上下文 (Temporary Context)
系统会在单次消息处理期间，为每个 Agent 保存一个临时的对话记录。你可以从 `context` 中获取 `agent_history` 并注入到消息列表中，提升 Agent 的连贯性。

### 示例代码 (handler.py)

```python
async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    user_prompt = args.get("prompt", "")
    ai_client = context.get("ai_client")
    agent_config = ai_client.agent_config
    
    # 1. 加载提示词和临时历史
    system_prompt = await _load_prompt()
    agent_history = context.get("agent_history", []) # 获取临时历史

    # 2. 构建消息序列
    messages = [{"role": "system", "content": system_prompt}]
    if agent_history:
        messages.extend(agent_history) # 注入历史
    messages.append({"role": "user", "content": f"用户需求：{user_prompt}"})

    # 3. 使用统一接口请求模型
    result = await ai_client.request_model(
        model_config=agent_config,
        messages=messages,
        call_type="agent:your_agent_name",
        tools=tools, # 如果有工具定义
    )
    
    # 提取内容
    content = result.get("choices", [{}])[0].get("message", {}).get("content") or ""
    return content
```

> [!NOTE]
> `agent_history` 仅在当前这条 QQ 消息的处理生命周期内有效，处理完后会自动丢弃，不会造成长期记忆污染。

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
- **功能**：查询天气、热搜、历史、WHOIS、B 站信息等
- **适用场景**：天气查询、热点榜单、域名查询、B 站视频和 UP 主信息查询
- **子工具**：`weather_query`, `*hot`, `whois`, `bilibili_search`, `bilibili_user_info`

### entertainment_agent（娱乐助手）
- **功能**：运势、小说、创意内容与随机视频推荐等娱乐功能
- **适用场景**：查看运势、获取休闲内容、随机刷视频
- **子工具**：`horoscope`, `novel_search`, `ai_draw_one`, `video_random_recommend`
