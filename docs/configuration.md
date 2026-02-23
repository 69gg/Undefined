# 配置与热更新说明

Undefined 采用结构化的 `config.toml` 作为主配置文件，覆盖了账号、模型、安全、拓展与运行时环境等全方位设定。
为了方便生产环境平滑修改配置，系统内建了强大的 **热重载 (Hot Reload)** 支持。本文档将详尽解释每一个配置节点的作用。

---

## 快速导航
- [核心配置 `[core]`](#核心配置-core)
- [访问控制 `[access]`](#访问控制-access)
- [协议端 `[onebot]`](#协议端-onebot)
- [模型配置 `[models.*]`](#模型配置-models)
- [认知记忆 `[cognitive]`](#认知记忆-cognitive)
- [多模态与工具生态](#多模态与工具生态)
- [高级与网络设置](#高级与网络设置)
- [热重载机制说明](#配置热重载说明)
- [MCP 与 Anthropic Skills 挂载](#mcp-与-anthropic-skills-挂载)

---

## 核心配置 `[core]`

管理机器人的身份与最高权限。

```toml
[core]
bot_qq = 12345678            # 机器人自身的 QQ 号
superadmin_qq = 87654321     # 系统级超级管理员 QQ 号（唯一，具备最高指令执行权限）
admin_qq = []                # 预置的基础管理员 QQ 列表
forward_proxy_qq = 0         # 音频等特殊格式转发的代理 QQ（可选）

process_every_message = true    # 【核心开关】是否处理所有群消息。强烈建议开启，否则无法形成有效记忆
process_private_message = true  # 是否处理私聊消息
process_poke_message = true     # 是否响应好友或群友的双击拍一拍事件

context_recent_messages_limit = 20 # 每次请求大模型时，附带的最近聊天记录条数（上下文感知）
ai_request_max_retries = 2      # 请求大模型失败后的最大重试次数（防止网络抖动导致的响应丢失）
```

---

## 访问控制 `[access]`

精准把控你的机器人能在哪里被使用，以及谁可以使用。
详细的高阶群管设定与鉴权说明，请参考 [《访问控制指南》](access-control.md)。

```toml
[access]
# 访问控制模式可选：
# - "off": 关闭控制，所有群与私聊可用
# - "blacklist": 黑名单模式（仅屏蔽名单内的群/人）
# - "allowlist": 白名单模式（仅允许名单内的群/人，最为安全）
mode = "off"

allowed_group_ids = []       # 允许的群聊白名单
blocked_group_ids = []       # 屏蔽的群聊黑名单（优先级高于白名单）
allowed_private_ids = []     # 允许的私聊白名单
blocked_private_ids = []     # 屏蔽的私聊黑名单

# 绕过设定：防止误锁超管
superadmin_bypass_allowlist = true        # 超管私聊无视 allowed_private_ids 白名单限制
superadmin_bypass_private_blacklist = false # 超管私聊是否无视 blocked_private_ids 限制
```

---

## 协议端 `[onebot]`

用于通过 WebSocket 挂载诸如 NapCat、Lagrange.Core 等 OneBot V11 实现端。

```toml
[onebot]
ws_url = "ws://127.0.0.1:3001"   # 协议端暴露的 WebSocket 正向连接地址
token = ""                       # 鉴权 Token（若协议端配置了则必须对应填写）
```

---

## AI 模型配置 `[models.*]`

Undefined 按不同的职责，在内部划分了多种专用模型的投递管线：对话、视觉、智能体执行、安全稽查、以及记忆向量化。
每个具体分类（如 `[models.chat]`）的可用底层字段高度一致：

**通用核心字段：**
- `api_url`：兼容 OpenAI 的 Base URL（形如 `https://api.openai.com/v1`）
- `api_key`：模型密钥
- `model_name`：调用的模型名称（如 `gpt-4o-mini`, `deepseek-chat`）
- `queue_interval_seconds`：速率限制（控制该请求管线发车的冷却时间，单位：秒）
- `max_tokens`：模型最大输出长度限制
- `thinking_enabled`：是否为支持思维链的模型开启推理能力

### 对话核心模型 `[models.chat]`
处理常规聊天指令的主力模型。

```toml
[models.chat]
api_url = "https://apiKeyUrl/v1"
api_key = "sk-xxxxxxxx"
model_name = "gpt-4o"
queue_interval_seconds = 1.0

# 深思/推理模型专属设定 (DeepSeek R1/O1 等)
thinking_enabled = false
thinking_budget_tokens = 20000 
thinking_include_budget = true
# 针对某些网关不支持思维链混合 Tool Calls 返回 400 的兜底参数：
thinking_tool_call_compat = false 
```

### 更多专属管线模型
建议针对不同的业务场景配置专用的廉价/高性能模型，以优化成本。
- `[models.vision]`：**视觉提取**，当用户发图或要求解析图片时使用（需填入支持 Vision 的模型如 `gpt-4o`, `claude-3-5-sonnet`）。
- `[models.agent]`：**智能体执行**，长时并发任务（搜索、写代码、查运势）的主力干将。
- `[models.security]`：**安全稽查**，过滤黄赌毒、提示词注入攻击。建议配置小且快的模型。
- `[models.historian]`：**记忆史官**，异步在后台总结归纳长期记忆，需要长上下文支撑。
- `[models.embedding]` 与 `[models.rerank]`：文本向量化与召回排序，配合 [认知记忆系统](cognitive-memory.md) 使用。

---

## 认知记忆 `[cognitive]`

这是使得 Undefined 与众不同的大杀器——无阻塞自动侧写记忆网络。
详情请见 [《认知记忆系统详解》](cognitive-memory.md)。

```toml
[cognitive]
enabled = true          # 强烈建议开启，否则无法形成长时记忆（需配置 embedding）

[cognitive.query]
auto_top_k = 3          # 每次对话自动根据语义召回匹配的前 3 条古老记忆
# 其他高阶设定包括：
# time_decay_enabled = true （按时间衰减修正记忆权重）
# time_decay_half_life_days_auto = 14.0 （半衰期）

[cognitive.historian]
rewrite_max_retry = 2               # 绝对化改写失败时的最大重试次数
recent_messages_inject_k = 12       # 提供给史官的最近消息参考条数（0=禁用）
recent_message_line_max_len = 240   # 每条最近消息参考的最大长度
source_message_max_len = 800        # 当前触发消息原文的最大长度
```

以上 `cognitive.historian.*` 参数支持热更新，可在不中断服务的情况下微调史官上下文密度。

---

## 工具生态与多模态

### Web UI `[webui]`
内建的可视化配置终端。
```toml
[webui]
url = "127.0.0.1"      # WebUI 绑定的地址，0.0.0.0 为公开网络可见
port = 8787            # 启动端口
password = "changeme"  # 【重要】默认密码禁止登入，首次运行务必修改
```

### Bilibili 提取 `[bilibili]`
原生零延迟视频解析。
```toml
[bilibili]
auto_extract_enabled = false   # 开启后，任何包含 B 站链接/BV 号的话语都会触发展开和下载
cookie = ""                    # 建议填入含有 SESSDATA 的 B 站完整网页 cookie 以突破风控
prefer_quality = 80            # 80(1080P), 64(720P), 32(480P)
```

### 代码沙盒 `[code_delivery]`
基于 Docker 的绝对安全代码试运行终端。
```toml
[code_delivery]
enabled = true
docker_image = "ubuntu:24.04"  # 使用镜像环境作为运行试错场所
```

### 本地知识库 `[knowledge]`
允许挂载本地文本到系统的知识资产中进行 QA。
```toml
[knowledge]
enabled = false
base_dir = "knowledge"    # 读取该目录下的所有纯本文
auto_scan = false         # 对文本进行自动修改侦测与切割
```

---

## 配置热重载说明

Undefined 系统高度现代化的一个标志是：**大部分修改可以实时生效，无需重启进程。**

### 🟢 实时生效（保存 `.toml` 即生效）
- `[access]` 黑白名单（新增/移除免封免重启）
- `[models.*]` 内的模型名称、API Key、Url 甚至 `queue_interval_seconds`（无缝热切大模型，队列频率瞬间改变）
- `[messages]` 文件体积阀值
- 所有的 `[features]` 及 `[easter_egg]` 特性

### 🔴 必须重启进程才能生效
以下字段牵扯到底层物理绑定、网络套接字监听及循环线程开启：
- `[logging]` 相关的日志落盘配置（等级、大小、路径）
- `[onebot]` WS 连接信息（`ws_url` 和 `token`）
- `[webui]` 控制台网络监听信息（`url` / `port` / `password`）

---

## MCP 与 Anthropic Skills 挂载

除了常规的配置，你可以利用标准协议赋予机器人访问整个系统与外网的能力。

### MCP (Model Context Protocol) 接入

MCP 允许 AI 通过标准化管道调用外部系统（比如 GitHub 读取、数据库执行查询动作等）。

1. 复制配置文件模板并配置服务器：
   `cp config/mcp.json.example config/mcp.json`
2. 在 `config.toml` 加入挂载点：
   ```toml
   [mcp]
   config_path = "config/mcp.json"
   ```

**Agent 私有 MCP 挂载：**
你也可以单独为某个子 Agent 挂载其独有的工具。在其目录下放置 `mcp.json` 即可（如 `src/Undefined/skills/agents/web_agent/mcp.json`，已默认内置 `playwright` 网页抓取框架）。

### Anthropic Skills 注入

无需书写代码逻辑，仅通过放置 `.md` 文档就能为 AI 模型动态提供最佳实践和 SOP 流程指南！
- 具体参考官方库：[github.com/anthropics/skills](https://github.com/anthropics/skills)
- 放置路径：`src/Undefined/skills/anthropic_skills/<skill-name>/SKILL.md`（系统会自动将其注册为内置工具）。
