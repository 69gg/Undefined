# Tool Search 按需工具加载

Tool Search 用于减少主 AI 每次请求携带的 function schema 数量。系统仍在本地保留完整、可执行的工具注册表，但只把配置为始终加载的工具和已经检索到的工具 schema 发送给模型；其余工具仅以名称目录注入 Prompt。

该功能默认关闭，关闭时行为与以往一致：主 AI 收到经过会话权限过滤后的完整工具列表。

## 启用与配置

在 `config.toml` 中配置：

```toml
[skills]
tool_search_enabled = true
tool_search_always_loaded = ["send_message", "end"]
tool_search_max_results = 5
```

| 配置项 | 默认值 | 说明 |
|---|---:|---|
| `tool_search_enabled` | `false` | 仅为主 AI 启用按需 schema 投影 |
| `tool_search_always_loaded` | `["send_message", "end"]` | 每次主 AI 请求开始时直接暴露的注册表工具 |
| `tool_search_max_results` | `5` | 单次搜索最多加载的 schema 数，最小为 `1` |

环境变量分别为 `TOOL_SEARCH_ENABLED`、`TOOL_SEARCH_ALWAYS_LOADED` 和 `TOOL_SEARCH_MAX_RESULTS`；工具列表使用逗号分隔，例如 `send_message,end`。配置支持热更新，但只影响新的 `ask()`，不会改变已经运行中的请求快照。完整配置表见[配置说明](configuration.md)。

## 工作流程

每次主 AI `ask()` 会创建独立的 `ToolSearchSession`：

1. 先应用当前会话的权限与功能过滤，再从过滤结果建立工具快照；未授权工具不会进入名称目录或搜索索引。
2. 首轮只发送 `tool_search`、`tool_search_always_loaded` 中存在的工具，以及未配置隐藏或预取失败的工具 schema。
3. 其余规范工具名按稳定顺序写入 `<available_deferred_tools>`；目录不含描述、参数或 schema。
4. 模型调用 `tool_search` 后，命中的 schema 加入本次请求的已加载集合。
5. 新加载工具从下一轮模型请求开始可调用。搜索和目标工具不能在同一轮调用。

已加载集合在一次 `ask()` 内只增不减；新的用户请求会重新创建最小集合。工具注册表或 MCP 热重载也只影响下一次 `ask()`。

## 查询语法

虚拟工具接口为：

```text
tool_search(query: string, max_results?: integer)
```

支持以下查询方式：

| 查询 | 行为 |
|---|---|
| `select:web_agent,info_agent` | 按规范名称精确加载多个工具；优先匹配目录中的精确拼写，再按大小写不敏感方式解析并去重 |
| `group.get_member_info` | 完整名称精确匹配，优先于关键词搜索 |
| `member_info` | 关键词中的点号、下划线和连字符会与工具名使用相同规则拆分，可匹配 `group.get_member_info` |
| `member avatar` | 按空格分词，在工具名、参数名、工具描述和参数描述中搜索 |
| `member +user` | `+user` 为必需词；名称、参数名或描述均不包含该词的候选会先被排除 |

关键词中的 `.`、`_`、`-` 与工具名索引使用一致的分隔规则，例如 `search_songs` 可以匹配 `music.search_songs`，不会误命中仅在描述中引用该名称的工具。结果按名称命中优先，其次考虑参数名和描述；最终按得分降序、规范名称升序稳定排序。`max_results` 只能缩小配置上限，不能扩大单次加载数量，`select:` 也受同一上限约束。

工具返回固定 JSON 字段：

| 字段 | 说明 |
|---|---|
| `loaded` | 本次新加载、将在下一轮可见的规范工具名 |
| `already_loaded` | 已经加载的匹配项，包括 `tool_search` 本身 |
| `not_found` | 精确选择中不存在的名称，或完全无命中的关键词查询 |
| `truncated` | 匹配数是否超过本次结果上限 |
| `total_deferred_tools` | 本次请求最初的延迟工具总数，不是剩余数量 |

模型应优先使用目录中的准确名称执行 `select:`，并始终以新一轮实际收到的 tools schema 及名称为准。工具名中的点号可能在发往特定模型服务时编码为配置的分隔符，该映射不改变本地规范名称。

## 边界与兼容性

- Tool Search 只作用于主 AI；子 Agent 仍使用各自完整且经过白名单过滤的私有工具集。
- 它不改变工具注册、执行、别名、MCP 连接或 Runtime Tool Invoke API，只改变发给模型的 schema 投影。
- `prefetch_tools_hide = true` 的工具仅在预取成功后隐藏；抛出异常或返回“未找到”时，本次 `ask()` 不会自动重试预取，并会持续向模型暴露其 schema，允许模型按需调用。为 `false` 时无论预取结果如何都会随首轮工具一起暴露。
- 如果完整注册表已经存在名为 `tool_search` 的真实工具，该请求记录错误并回退全量工具，且因不生成 `<available_deferred_tools>` 目录而禁用 Tool Search Prompt 规则，避免模型把真实工具误当作虚拟加载器。
- 当权限过滤后没有延迟工具时，请求直接使用全量可用工具，不额外保留无意义的搜索会话。
- Chat Completions 与 Responses 使用同一套普通 function tool 逐轮扩展逻辑，不依赖服务商专属 Tool Search 协议。

## 与 handler 延迟导入的区别

两种“延迟加载”发生在不同层：

- 注册表延迟导入：启动时读取 `config.json` 建立本地 schema，首次执行工具时才导入对应 `handler.py`，用于降低启动成本。
- Tool Search 按需投影：完整 schema 和可执行注册项已存在于本地注册表，但模型初始只看到少量 schema，用于降低 Prompt 与请求体积。

两者可以同时生效。Tool Search 命中某个工具只会让其 schema 在下一轮对模型可见；真正调用该工具时，注册表才按原机制导入并执行 handler。
