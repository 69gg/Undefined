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
model_name = "gpt-4o-mini"
max_tokens = 4096
api_mode = "openai.chat_completions"
reasoning_enabled = false
reasoning_effort = "medium"
thinking_enabled = false
thinking_budget_tokens = 0
thinking_tool_call_compat = true
reasoning_content_replay = true
responses_tool_choice_compat = false
responses_force_stateless_replay = false
```

说明：
- `api_mode = "openai.chat_completions"` 时，`thinking_enabled` 发送兼容接口常用的 `thinking`，`reasoning_enabled` 发送顶层 `reasoning_effort`。回放支持 `reasoning_content`、OpenRouter `reasoning_details`、签名和加密字段。
- `api_mode = "openai.responses"` 时，多轮工具调用默认使用 `previous_response_id + function_call_output`；`responses_force_stateless_replay=true` 才改为完整 `output` items 重放。工具结果使用 `call_id` 关联，`function_call.id` 仅保留模型返回的合法 `fc_*` id。
- `api_mode = "anthropic.messages"` 时使用官方 `AsyncAnthropic` Messages SDK，并转换 system、图片、工具和 tool result；`max_tokens` 必须为正整数，`thinking_include_budget=false` 使用 adaptive thinking，手动预算必须至少 1024 且小于本次 `max_tokens`。
- `reasoning_effort` 保持自定义输入：`adaptive` 原样发送，其余值也原样透传；具体字段位置由 `api_mode` 自动决定，不再需要 style 配置。
- `reasoning_content_replay` 默认 `true`，优先按历史顺序原样回传全部原生推理结构；设为 `false` 会过滤明文、summary、签名和加密推理材料。
- `thinking_tool_call_compat` 默认 `true`，用于在本地历史保留可读 `reasoning_content`，供日志和旧历史回退。

兼容的环境变量（会覆盖 `config.toml`）：

```env
AGENT_MODEL_API_URL=
AGENT_MODEL_API_KEY=
AGENT_MODEL_NAME=
AGENT_MODEL_MAX_TOKENS=4096
AGENT_MODEL_API_MODE=openai.chat_completions
AGENT_MODEL_REASONING_ENABLED=false
AGENT_MODEL_REASONING_EFFORT=medium
AGENT_MODEL_REASONING_CONTENT_REPLAY=true
AGENT_MODEL_THINKING_ENABLED=false
AGENT_MODEL_THINKING_BUDGET_TOKENS=0
AGENT_MODEL_THINKING_TOOL_CALL_COMPAT=true
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
| `skills.intro_autogen_queue_interval` / `AGENT_INTRO_AUTOGEN_QUEUE_INTERVAL` | 队列发车间隔（秒，`0` 立即发车，`<0` 回退 `1.0`） | 1.0 |
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

### 1. 使用 `ai_client.submit_queued_llm_call`
不要直接使用 `httpx` 调用 API，而是使用 `context` 中提供的 `ai_client.submit_queued_llm_call`。它会自动：
- 记录 Token 使用情况到系统统计中。
- 只对当前 LLM 请求执行静默重试。
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
    messages.append({"role": "user", "content": user_prompt})

    # 3. 使用统一接口请求模型
    result = await ai_client.submit_queued_llm_call(
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
- **功能**：联网搜索、网页阅读、来源核验和最新信息获取。
- **适用场景**：新闻/公告/资料搜索、指定 URL 摘要、多来源对比、时效性问题核验。
- **不适用**：天气、金价、热搜、Whois、B 站、arXiv 检索等结构化查询；用户附件或文件解析。
- **子工具**：`grok_search`, `firecrawl_search`, `web_search`, `crawl_webpage`。
- **搜索优先级**：由 `[search].priority` 注入提示词引导，关闭的搜索工具会从 `web_agent` 工具列表中隐藏。
- **grok_search 参数**：使用 `search_request`，用自然语言完整叙述搜索要求，不要只传关键词。

### file_analysis_agent（文件分析助手）
- **功能**：分析用户提供的附件、内部 UID、URL、legacy file_id、arXiv 论文标识或 Bilibili 视频标识，提取文件内容。
- **适用场景**：PDF/Word/Excel/PPT/文本/代码/压缩包解析，图片、音频、视频等多模态内容识别，arXiv 论文 PDF 分析，Bilibili 视频内容分析。
- **不适用**：没有文件来源的开放式搜索、需要联网查资料的问题、执行文件或安全鉴定。
- **子工具**：`download_file`, `detect_file_type`, `read_text_file`, `extract_pdf`, `describe_pdf_page`, `extract_docx`, `extract_xlsx`, `extract_pptx`, `extract_archive`, `analyze_code`, `analyze_multimodal`, `cleanup_temp`；还可调用共享主工具 `arxiv_paper(output_mode=uid)` 与 `bilibili_video(output_mode=uid)` 获取待分析附件 UID。

### naga_code_analysis_agent（NagaAgent 代码分析助手）
- **功能**：只读分析 NagaAgent 项目的结构、源码、配置、构建、部署和实现细节。
- **适用场景**：追踪 NagaAgent 模块实现、目录结构、配置项、报错线索和项目内文档。
- **不适用**：Undefined 自身源码、用户上传文件、代码编写修改、执行验证或外部联网搜索。
- **子工具**：`read_file`, `list_directory`, `glob`, `search_file_content`, `read_naga_intro`。

### undefined_self_code_agent（Undefined 自身代码查阅助手）
- **功能**：只读查阅 Undefined 当前仓库的源码、测试、文档、资源、脚本、配置示例和 App 实现。
- **适用场景**：解释 Undefined 自身实现、定位模块、核对配置示例、查看测试覆盖。
- **访问范围**：`src/`, `scripts/`, `tests/`, `res/`, `docs/`, `apps/`, `README.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `config.toml.example`。
- **不适用**：写代码、改文件、运行命令、验证打包、NagaAgent 子模块、用户上传文件解析。
- **子工具**：`read_file`, `list_directory`, `glob`, `search_file_content`。

### info_agent（信息查询助手）
- **功能**：调用结构化工具完成参数明确的信息查询。
- **适用场景**：天气、金价、热搜、历史、Whois、网络诊断、测速、编码/哈希、B 站、QQ 等级、arXiv 检索。
- **不适用**：开放式网页搜索、网页阅读、来源核验、文件解析或长篇研究。
- **子工具**：`weather_query`, `gold_price`, `baiduhot`, `weibohot`, `douyinhot`, `history`, `whois`, `net_check`, `speed`, `tcping`, `base64`, `hash`, `bilibili_search`, `bilibili_user_info`, `qq_level_query`, `arxiv_search`。

### entertainment_agent（娱乐助手）
- **功能**：轻松互动、趣味内容和休闲创作。
- **适用场景**：AI 绘画、参考图生图、星座运势、趣味占卜、随机内容、Minecraft 皮肤/头像渲染、小说搜索、表情包或反应图需求。
- **不适用**：严肃专业建议、事实核验、新闻资料搜索、文件内容解析。
- **子工具**：`ai_draw_one`, `horoscope`, `minecraft_skin`, `renjian`, `wenchang_dijun`。

### summary_agent（消息总结助手）
- **功能**：按条数或时间范围拉取聊天记录并生成客观总结。
- **适用场景**：总结最近 N 条消息、过去一段时间的讨论、指定主题的结论、待办、参与者贡献和链接资源。
- **不适用**：实时监控、情绪评判、未来预测、脱离聊天记录的推测；`/summary` 与 `/sum` 斜杠命令由命令层直连 summary 模型。
- **子工具**：`fetch_messages`。

### code_delivery_agent（代码交付助手）
- **功能**：把代码需求实现为可交付的文件或工程。
- **适用场景**：单文件脚本/配置/文档交付，多文件工程创建、修改、调试、测试和打包，从空目录或 Git 仓库开始。
- **不适用**：只读源码讲解、用户上传文件解析、单纯资料调研。
- **子工具**：`init_docker`, `read`, `write`, `copy`, `delete`, `tree`, `glob`, `grep`, `diff`, `run_bash_command`, `todo`, `end`。
