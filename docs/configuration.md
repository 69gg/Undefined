# 配置详解（`config.toml`）

本文档是 Undefined 当前配置系统的完整说明，覆盖：
- 配置加载顺序与解析规则
- 严格模式必填项
- 每个配置节与字段的用途、默认值、约束、回退行为
- 热更新与重启生效边界
- 兼容旧字段与环境变量迁移建议

建议搭配 [config.toml.example](../config.toml.example) 一起阅读。

---

## 1. 配置文件与加载机制

### 1.1 主配置文件
- 主文件：`config.toml`
- 示例模板：`config.toml.example`
- 启动 WebUI 时，如 `config.toml` 不存在，会自动用示例模板生成。

### 1.2 运行时本地文件
- `config.local.json`：运行时维护的本地管理员列表（如 `/addadmin`）。
- 该文件会与 `core.admin_qq` 合并。
- 该文件也在热更新监听范围内。

### 1.3 加载优先级
1. `config.toml` 中的显式值
2. 对应环境变量（仅当 TOML 该项缺失时兜底）
3. 代码默认值

说明：检测到环境变量兜底时会输出告警，建议迁移到 `config.toml` 统一管理。

### 1.4 解析与归一化规则
- 读取编码：`utf-8-sig`。
- 字符串：会做 `strip()`，空字符串通常视为未配置。
- 整数/浮点：非法值回退默认值。
- 布尔：支持 `true/false`、`1/0`、`yes/no`、`on/off`。
- URL 基址：`api_endpoints.*_base_url` 会自动去掉末尾 `/`。
- TOML 解析错误会给出具体行列、问题行和 Windows 路径提示。

---

## 2. 严格模式（`strict=True`）必填项

程序主流程使用严格模式加载配置。缺失以下字段会报错退出：
- `core.bot_qq`
- `core.superadmin_qq`
- `onebot.ws_url`
- `models.chat.api_url` / `api_key` / `model_name`
- `models.vision.api_url` / `api_key` / `model_name`
- `models.agent.api_url` / `api_key` / `model_name`
- 若 `knowledge.enabled=true`，还必须配置：`models.embedding.api_url` / `model_name`

> 注意：`cognitive.enabled=true` 时如果 embedding 未配置，不会直接抛错退出，而是启动时自动降级禁用认知记忆并打印告警。

---

## 3. 最小可运行配置示例

```toml
[core]
bot_qq = 123456
superadmin_qq = 654321

[onebot]
ws_url = "ws://127.0.0.1:3001"
token = ""

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"
```

---

## 4. 全量字段说明

### 4.1 `[core]` 机器人核心行为

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `bot_qq` | `0` | 机器人 QQ 号 | `>0` 才合法（严格模式必填） |
| `superadmin_qq` | `0` | 超级管理员 QQ | `>0` 才合法（严格模式必填） |
| `admin_qq` | `[]` | 初始管理员列表 | 与 `config.local.json` 中动态管理员合并 |
| `forward_proxy_qq` | `0` | 音频转发代理 QQ（可选） | `<=0` 视为 `None` |
| `process_every_message` | `true` | 群聊是否处理每条消息 | 关闭后仅处理 @ 触发 |
| `process_private_message` | `true` | 是否处理私聊回复 | 关闭后私聊只记录历史，不回复 |
| `process_poke_message` | `true` | 是否响应拍一拍 | 关闭后忽略 poke |
| `context_recent_messages_limit` | `20` | 注入到提示词的最近历史条数 | 自动钳制到 `0..200` |
| `ai_request_max_retries` | `2` | 模型请求失败重试次数 | 自动钳制到 `0..5`；此项变更需重启 |

---

### 4.2 `[access]` 访问控制

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `mode` | `"off"` | 模式：`off` / `blacklist` / `allowlist` | 非法值回退 `off` |
| `allowed_group_ids` | `[]` | 群白名单 | `allowlist` 模式生效 |
| `blocked_group_ids` | `[]` | 群黑名单 | `blacklist` 模式生效（优先） |
| `allowed_private_ids` | `[]` | 私聊白名单 | `allowlist` 模式生效 |
| `blocked_private_ids` | `[]` | 私聊黑名单 | `blacklist` 模式生效 |
| `superadmin_bypass_allowlist` | `true` | 超管私聊是否绕过私聊白名单 | 仅私聊，不影响群 |
| `superadmin_bypass_private_blacklist` | `false` | 超管私聊是否绕过私聊黑名单 | 仅私聊 |

补充：
- 若 `access.mode` 未设置，但任一名单非空，会进入兼容模式 `legacy`（黑白名单联动）；建议显式设置 `mode`。
- `blocked_*` 优先于 `allowed_*`。

---

### 4.3 `[onebot]` 协议端连接

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `ws_url` | `"ws://127.0.0.1:3001"` | OneBot WebSocket 地址 | 严格模式必填 |
| `token` | `""` | OneBot token | 同时用于 URL 参数与 `Authorization` 头 |

`onebot.*` 变更需要重启进程才能生效。

---

### 4.4 `[models]` 模型配置总览

### 4.4.1 通用字段（chat/vision/security/agent/historian）

| 字段 | 含义 |
|---|---|
| `api_url` | OpenAI-compatible 基址（建议 `.../v1`） |
| `api_key` | API Key |
| `model_name` | 模型名 |
| `max_tokens` | 最大输出 token（vision 无此字段） |
| `queue_interval_seconds` | 该模型请求队列发车间隔（秒） |
| `thinking_enabled` | 是否启用思维链参数 |
| `thinking_budget_tokens` | thinking 预算 |
| `thinking_include_budget` | 是否发送 budget_tokens |
| `thinking_tool_call_compat` | Tool Calls 兼容模式（回传 reasoning_content） |

兼容字段（旧配置）：
- `models.<x>.deepseek_new_cot_support`
  - 若开启：等效默认 `thinking_include_budget=false` + `thinking_tool_call_compat=true`
  - 显式设置新字段时，以新字段为准。

### 4.4.2 `[models.chat]` 主对话模型

默认：
- `max_tokens=8192`
- `queue_interval_seconds=1.0`（`<=0` 回退 `1.0`）
- `thinking_budget_tokens=20000`

### 4.4.3 `[models.vision]` 视觉模型

默认：
- `queue_interval_seconds=1.0`（`<=0` 回退 `1.0`）
- `thinking_budget_tokens=20000`

### 4.4.4 `[models.security]` 安全模型

字段：
- 额外开关：`enabled=true`
- 默认：`max_tokens=100`，`thinking_budget_tokens=0`

关键回退逻辑：
- 若 `api_url/api_key/model_name` 任一缺失，会自动回退为 chat 模型（并告警）。

### 4.4.5 `[models.agent]` Agent 执行模型

默认：
- `max_tokens=4096`
- `queue_interval_seconds=1.0`（`<=0` 回退 `1.0`）

### 4.4.6 `[models.historian]` 史官模型

- 用于认知记忆后台改写。
- 若整个节缺失或为空：完整回退到 `models.agent`。
- 若部分字段缺失：逐项继承 agent 配置。
- `queue_interval_seconds<=0` 时回退到 agent 的间隔。

### 4.4.7 模型池

相关节：
- `[models.chat.pool]`
- `[models.agent.pool]`
- `[[models.chat.pool.models]]`
- `[[models.agent.pool.models]]`

字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `false` | 当前池开关 |
| `strategy` | `"default"` | `default` / `round_robin` / `random` |
| `models` | `[]` | 池中模型列表 |

`models` 条目支持字段：
- `model_name`（必填）
- `api_url`/`api_key`/`max_tokens`/`queue_interval_seconds`/`thinking_*`（可选，缺省继承主模型）

生效条件（全部满足才启用池）：
1. `features.pool_enabled=true`
2. 对应池 `enabled=true`
3. 池列表非空

### 4.4.8 `[models.embedding]` 嵌入模型

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_url` | `""` | 嵌入 API 地址 |
| `api_key` | `""` | API Key |
| `model_name` | `""` | 模型名 |
| `queue_interval_seconds` | `1.0` | 发车间隔 |
| `dimensions` | `0` | 向量维度；`0`/空视为 `None`（模型默认） |
| `query_instruction` | `""` | 查询前缀 |
| `document_instruction` | `""` | 文档前缀 |

### 4.4.9 `[models.rerank]` 重排模型

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `api_url` | `""` | rerank API 地址 |
| `api_key` | `""` | API Key |
| `model_name` | `""` | 模型名 |
| `queue_interval_seconds` | `1.0` | `<=0` 回退 `1.0` |
| `query_instruction` | `""` | 查询前缀 |

---

### 4.5 `[knowledge]` 本地知识库

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `false` | 是否启用知识库 | 启用后需 embedding 配置完整 |
| `base_dir` | `"knowledge"` | 知识库根目录 | |
| `auto_scan` | `false` | 是否定时扫描文件变化 | |
| `auto_embed` | `false` | 是否自动执行嵌入 | |
| `scan_interval` | `60.0` | 扫描间隔（秒） | `<=0` 回退 `60.0` |
| `embed_batch_size` | `64` | 批大小 | `<=0` 回退 `64` |
| `chunk_size` | `10` | 分块窗口大小（按行） | `<=0` 回退 `10` |
| `chunk_overlap` | `2` | 相邻块重叠行数 | `<0` 回退 `0` |
| `default_top_k` | `5` | 召回数量 | `<=0` 回退 `5` |
| `enable_rerank` | `false` | 是否启用二阶段重排 | 自动约束见下 |
| `rerank_top_k` | `3` | 重排后返回数量 | `<=0` 回退 `3` |

重排约束：
- `rerank_top_k` 必须 `< default_top_k`。
- 若不满足，自动回退为 `default_top_k - 1`。
- 若 `default_top_k <= 1`，则自动禁用 rerank。

自动扫描行为：
- `auto_scan=true` 且 `auto_embed=true`：持续周期扫描。
- `auto_scan=false` 且 `auto_embed=true`：仅启动时做一次初始扫描。
- `auto_embed=false`：仅手动触发。

---

### 4.6 `[logging]` 日志

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `level` | `"INFO"` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `file_path` | `"logs/bot.log"` | 日志文件路径 |
| `max_size_mb` | `10` | 单文件轮转大小（MB） |
| `backup_count` | `5` | 轮转保留数量 |
| `tty_enabled` | `false` | 是否输出到终端 |
| `log_thinking` | `true` | 是否记录思维链日志 |

说明：
- `max_size_mb` 运行时会转成字节。
- `logging.level/file_path/max_size_mb/backup_count/tty_enabled` 变更需重启。
- `log_thinking` 可热更新（请求时动态读取）。

---

### 4.7 `[tools]` Tool Schema 兼容配置

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `dot_delimiter` | `"-_-"` | 将工具名中的 `.` 映射为分隔符 | 仅允许 `[a-zA-Z0-9_-]` 且不能含 `.`，非法回退默认 |
| `description_truncate_enabled` | `false` | 是否按长度截断工具描述 | |
| `description_max_len` | `1024` | 工具描述最大长度 | `<=0` 时内部使用默认 1024 |
| `sanitize_verbose` | `false` | 输出工具清洗明细日志 | |
| `description_preview_len` | `160` | 日志预览长度 | `<=0` 时内部使用默认 160 |

补充：描述清洗（控制字符、空白规整等）始终开启；`description_truncate_enabled` 仅控制“长度截断”。

---

### 4.8 `[features]` 功能总开关

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `nagaagent_mode_enabled` | `false` | 切换 NagaAgent 提示词和相关 Agent 暴露 |
| `pool_enabled` | `false` | 多模型池全局总开关 |

---

### 4.9 `[easter_egg]` 彩蛋行为

| 字段 | 默认值 | 说明 | 取值 |
|---|---:|---|---|
| `agent_call_message_enabled` | `"none"` | 调用提示模式 | `none` / `agent` / `tools` / `all` / `clean` |
| `keyword_reply_enabled` | `false` | 群聊关键词自动回复 | 布尔 |

兼容：历史字段 `[core].keyword_reply_enabled` 仍可读取，建议迁移到 `[easter_egg]`。

---

### 4.10 `[history]` 历史消息

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `max_records` | `10000` | 每个会话最多保留条数 |

说明：该值主要在 `MessageHistoryManager` 初始化时使用，运行中修改建议重启后再观察效果。

---

### 4.11 `[skills]` 技能系统与 Agent 介绍

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `hot_reload` | `true` | 是否启用技能热重载 |
| `hot_reload_interval` | `2.0` | 扫描间隔（秒） |
| `hot_reload_debounce` | `0.5` | 去抖时间（秒） |
| `intro_autogen_enabled` | `true` | 是否自动生成 agent intro |
| `intro_autogen_queue_interval` | `1.0` | intro 生成队列发车间隔 |
| `intro_autogen_max_tokens` | `8192` | intro 生成上限 |
| `intro_hash_path` | `.cache/agent_intro_hashes.json` | intro hash 缓存 |
| `prefetch_tools` | `["get_current_time"]` | 预先执行并注入 system 的工具列表 |
| `prefetch_tools_hide` | `true` | 预取后是否从 tool list 隐藏该工具 |

补充：
- `prefetch_tools` 未配置时默认会注入 `get_current_time`。
- `hot_reload_interval/debounce` 还会用于配置热更新监听器本身。

---

### 4.12 `[search]` 搜索

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `searxng_url` | `""` | SearXNG 地址；为空则禁用搜索包装器 |

该项可热更新，运行时会重建搜索客户端。

---

### 4.13 `[proxy]` 代理

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `use_proxy` | `true` | 是否允许相关工具使用代理 |
| `http_proxy` | `""` | HTTP 代理地址 |
| `https_proxy` | `""` | HTTPS 代理地址 |

环境变量兜底：
- 若 TOML 未配置 `http_proxy` / `https_proxy`，会尝试 `HTTP_PROXY` / `HTTPS_PROXY`。

---

### 4.14 `[network]` 网络请求默认参数

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `request_timeout_seconds` | `30.0` | 默认请求超时（秒） | `<=0` 回退 `480.0` |
| `request_retries` | `0` | 默认重试次数 | 自动钳制到 `0..5` |

---

### 4.15 `[api_endpoints]` 第三方 API 基址

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `xxapi_base_url` | `https://v2.xxapi.cn` | XXAPI 基址 |
| `xingzhige_base_url` | `https://api.xingzhige.com` | 星之阁基址 |

说明：以上值会自动去除末尾 `/`。

---

### 4.16 `[xxapi]` 与 `[weather]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `xxapi.api_token` | `""` | XXAPI token（前往 https://xxapi.cn 获取）|

说明：`weather.api_key` 当前主要作为兼容保留项。

---

### 4.17 `[token_usage]` Token 归档

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `max_size_mb` | `5` | 主文件超过该大小后归档，`<=0` 禁用 |
| `max_archives` | `30` | 最大归档数量，`<=0` 不限制 |
| `max_total_mb` | `0` | 归档总大小上限，`<=0` 禁用 |
| `archive_prune_mode` | `"delete"` | 清理模式：`delete` / `merge` / `none` |

模式别名：
- `delete` 兼容 `prune/drop`
- `merge` 兼容 `repack/lossless`
- `none` 兼容 `keep/off/disable`

---

### 4.18 `[mcp]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `config_path` | `config/mcp.json` | MCP 配置文件路径 |

可配合 `config/mcp.json.example` 使用。

---

### 4.19 `[messages]` 消息工具限制

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `send_text_file_max_size_kb` | `512` | 文本文件发送上限（KB） | `<=0` 回退 `512` |
| `send_url_file_max_size_mb` | `100` | URL 文件发送上限（MB） | `<=0` 回退 `100` |

---

### 4.20 `[bilibili]` 自动提取

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `auto_extract_enabled` | `false` | 是否自动提取 B 站链接/BV | |
| `cookie` | `""` | 完整 Cookie 字符串 | 支持兼容旧字段 `sessdata`（不推荐） |
| `prefer_quality` | `80` | 目标清晰度（80/64/32） | |
| `max_duration` | `600` | 最大时长（秒），`0` 不限 | |
| `max_file_size` | `100` | 最大体积（MB），`0` 不限 | |
| `oversize_strategy` | `"downgrade"` | 超限策略 | 仅 `downgrade/info`，非法回退 `downgrade` |
| `auto_extract_group_ids` | `[]` | 功能级群白名单 | 空时跟随全局 access |
| `auto_extract_private_ids` | `[]` | 功能级私聊白名单 | 空时跟随全局 access |

---

### 4.21 `[code_delivery]` 代码交付 Agent

| 字段 | 默认值 | 说明 | 约束/回退 |
|---|---:|---|---|
| `enabled` | `true` | 启用 Code Delivery Agent | |
| `task_root` | `data/code_delivery` | 任务根目录 | |
| `docker_image` | `ubuntu:24.04` | Docker 镜像 | |
| `container_name_prefix` | `code_delivery_` | 容器名前缀 | |
| `container_name_suffix` | `_runner` | 容器名后缀 | |
| `default_command_timeout_seconds` | `0` | 默认命令超时，`0` 为不限时 | 若该字段缺失，内部回退到 600 秒 |
| `max_command_output_chars` | `20000` | 命令输出截断阈值 | |
| `default_archive_format` | `zip` | 归档格式 | 仅 `zip/tar.gz`，非法回退 `zip` |
| `max_archive_size_mb` | `200` | 归档大小上限 | |
| `cleanup_on_finish` | `true` | 任务结束后清理容器和目录 | |
| `cleanup_on_start` | `true` | 启动时清理残留容器和目录 | |
| `llm_max_retries_per_request` | `5` | LLM 连续失败阈值（预留） | |
| `notify_on_llm_failure` | `true` | 连续失败是否通知（预留） | |
| `container_memory_limit` | `""` | Docker `--memory` | 空表示不限 |
| `container_cpu_limit` | `""` | Docker `--cpus` | 空表示不限 |
| `command_blacklist` | 内置危险命令列表 | 命令黑名单（支持通配） | 运行时同时做 `fnmatch` 与子串匹配 |

---

### 4.22 `[webui]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `url` | `127.0.0.1` | WebUI 监听地址 |
| `port` | `8787` | WebUI 端口（1..65535） |
| `password` | `changeme` | WebUI 登录密码 |

关键行为：
- 默认密码 `changeme` 禁止登录，必须先修改。
- 未配置或为空时，会回退默认密码并标记为“默认密码模式”。
- `webui.url/port/password` 修改需重启 WebUI 进程（机器人主进程中也属于重启生效类）。

---

### 4.23 `[api]` Runtime API / OpenAPI

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 是否启用主进程 Runtime API |
| `host` | `127.0.0.1` | Runtime API 监听地址 |
| `port` | `8788` | Runtime API 端口（1..65535） |
| `auth_key` | `changeme` | 请求头鉴权密钥（`X-Undefined-API-Key`） |
| `openapi_enabled` | `true` | 是否暴露 `/openapi.json` |

关键行为：
- Runtime API 仅在主进程 `Undefined` 中启动，WebUI 通过后端代理调用。
- WebUI 会自动读取 `config.toml` 的 `api.auth_key` 并转发，不在前端暴露密钥。
- 默认密钥 `changeme` 仅用于初始开发环境，生产请务必替换。

详见 [docs/openapi.md](openapi.md)。

---

### 4.24 `[cognitive]` 认知记忆

### 4.24.1 根配置

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `enabled` | `true` | 开启认知记忆 |
| `bot_name` | `Undefined` | 史官改写中使用的 bot 名称 |

说明：当前版本解析器尚未从 `config.toml` 显式读取 `cognitive.bot_name`，运行时会保持默认值 `Undefined`。

### 4.24.2 `[cognitive.vector_store]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/chromadb` | Chroma 存储目录 |

### 4.24.3 `[cognitive.query]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `auto_top_k` | `3` | 自动注入召回条数 |
| `enable_rerank` | `true` | 认知检索是否启用 rerank |
| `recent_end_summaries_inject_k` | `30` | 最近 end 摘要注入条数，`0` 禁用 |
| `time_decay_enabled` | `true` | 是否启用时间衰减加权 |
| `time_decay_half_life_days_auto` | `14.0` | 自动注入场景半衰期 |
| `time_decay_half_life_days_tool` | `60.0` | 工具检索场景半衰期 |
| `time_decay_boost` | `0.2` | 时间加权强度 |
| `time_decay_min_similarity` | `0.35` | 应用时间加权的相似度阈值 |
| `tool_default_top_k` | `12` | 工具调用默认 top-k |
| `profile_top_k` | `8` | 侧写检索 top-k |
| `rerank_candidate_multiplier` | `3` | 候选倍数（`top_k * multiplier`） |

### 4.24.4 `[cognitive.historian]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `rewrite_max_retry` | `2` | 绝对化改写最大重试 |
| `recent_messages_inject_k` | `12` | 注入给史官的近期消息条数 |
| `recent_message_line_max_len` | `240` | 每条近期消息最大字符数 |
| `source_message_max_len` | `800` | 当前触发消息最大字符数 |
| `poll_interval_seconds` | `1.0` | 队列轮询间隔 |
| `stale_job_timeout_seconds` | `300.0` | processing 超时回收阈值 |

### 4.24.5 `[cognitive.profile]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/profiles` | 侧写存储目录 |
| `revision_keep` | `5` | 保留历史版本数量 |

### 4.24.6 `[cognitive.queue]`

| 字段 | 默认值 | 说明 |
|---|---:|---|
| `path` | `data/cognitive/queues` | 队列目录 |
| `failed_max_age_days` | `30` | failed 文件保留天数 |
| `failed_max_files` | `500` | failed 文件上限 |
| `failed_cleanup_interval` | `100` | 处理多少次后触发清理 |
| `job_max_retries` | `3` | 单任务自动重试次数 |

---

## 5. 热更新与重启边界

### 5.1 热更新监听对象
- `config.toml`
- `config.local.json`

### 5.2 明确“需重启”的字段
以下变更会被记录为“需重启生效”：
- `core.ai_request_max_retries`
- `logging.level`
- `logging.file_path`
- `logging.max_size_mb`
- `logging.backup_count`
- `logging.tty_enabled`
- `onebot.ws_url`
- `onebot.token`
- `webui.url`
- `webui.port`
- `webui.password`
- `api.*`（`enabled/host/port/auth_key/openapi_enabled`）

### 5.3 明确“会执行热应用”的字段
- 模型发车间隔 / 模型名 / 模型池变更（队列间隔刷新）
- `skills.intro_autogen_*`（Agent intro 生成器配置刷新）
- `search.searxng_url`（搜索客户端刷新）
- `skills.hot_reload*`（技能热重载任务重启）
- `skills.hot_reload_interval/debounce`（配置热更新监听器自身重启）

### 5.4 其他字段
- `Config` 对象本身会更新。
- 具体功能是否“立刻体现”，取决于模块是“每次读取配置”还是“启动时缓存”。
- 对于行为不确定项，建议改完观察日志；必要时重启进程确认。

---

## 6. 兼容旧字段与隐藏字段

- `models.<x>.deepseek_new_cot_support`：旧 thinking 兼容开关。
- `[core].keyword_reply_enabled`：旧位置，建议迁移到 `[easter_egg]`。
- `[bilibili].sessdata`：旧字段，建议改为完整 `cookie`。
- `api_endpoints.jkyai_base_url`、`api_endpoints.seniverse_base_url`、`weather.api_key`：代码仍支持，模板中未显式列出。

---

## 7. 环境变量兜底（迁移建议）

虽然推荐统一写入 `config.toml`，但当前仍支持大量环境变量兜底，常用示例：
- `BOT_QQ` / `SUPERADMIN_QQ`
- `ONEBOT_WS_URL` / `ONEBOT_TOKEN`
- `CHAT_MODEL_API_URL` / `CHAT_MODEL_API_KEY` / `CHAT_MODEL_NAME`
- `VISION_MODEL_*` / `AGENT_MODEL_*` / `SECURITY_MODEL_*`
- `EMBEDDING_MODEL_*` / `RERANK_MODEL_*`
- `SEARXNG_URL`
- `HTTP_PROXY` / `HTTPS_PROXY`

建议：
1. 把长期配置迁移到 `config.toml`。
2. 环境变量只保留临时覆写或 CI 场景。

---

## 8. 运维建议（生产环境）

1. 首次部署先改 `webui.password`，避免默认密码模式。
2. 显式配置 `access.mode`，不要依赖 legacy 行为。
3. 启用 `knowledge`/`cognitive` 前先验证 embedding/rerank 配置是否齐全。
4. 若使用模型池，先确认 `features.pool_enabled=true`。
5. 修改 `onebot`、`logging`、`webui`、`ai_request_max_retries` 后直接重启。
6. 观察启动日志中的 `[配置]` 告警，优先处理“自动回退”信息。
