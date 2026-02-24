# 认知记忆系统

## 概述

认知记忆系统是 Undefined 的三层分层记忆架构，模拟人类记忆机制：

- **短期记忆**（`end.memo`）：每轮对话结束自动记录行动备忘，最近 N 条始终注入，保持短期连续性，零配置开箱即用。
- **认知记忆**（`end.observations` + `cognitive.*`）：核心层，AI 在每轮对话中主动观察并提取用户/群聊事实（`observations`），经后台史官异步改写为绝对化事件并存入 ChromaDB 向量库，支持语义检索；当对话中出现新信息（偏好、身份、习惯等）时，史官自动合并更新 Markdown 侧写文件，下次对话时注入 prompt。
- **手动长期记忆**（`memory.*`）：AI 手动维护的少量高价值置顶事实，每轮固定注入，支持增删改查。

与旧 `end_summaries` 的区别：

| | 旧模式（end_summaries） | 认知记忆 |
|---|---|---|
| 存储 | 时序列表（JSON） | 向量数据库（ChromaDB） |
| 召回 | 全量注入（最近 N 条） | 语义检索（相关 top_k 条） |
| 侧写 | 无 | 自动生成用户/群侧写 |
| 前台延迟 | 同步写入 | 零延迟（文件队列异步） |
| 跨群隔离 | 无 | ChromaDB where 硬过滤 |

开启认知记忆后，旧 `end_summaries.json` 仍保持双写，随时可回退。

---

## 快速启用

最小配置（在 `config.toml` 中添加）：

```toml
[cognitive]
enabled = true

[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "text-embedding-3-small"
```

> `models.embedding` 是必要前提。未配置时，即使 `cognitive.enabled = true`，启动时也会自动降级并打印警告。

启动后验证：

```bash
# 对话结束后，检查队列和向量库目录是否生成
ls data/cognitive/queues/
ls data/cognitive/chromadb/
```

---

## 架构说明

### 前台零阻塞

AI 调用 `end` 工具结束对话时，只做一次文件落盘（p95 < 5ms），不等待 LLM 改写或向量入库：

```
用户消息 → AI 处理 → end 工具
                        └─ 写 pending/{job_id}.json  ← 前台唯一操作
                        └─ 写 end_summaries.json     ← 旧模式双写
```

`end` 字段语义：

- `memo`：记录 AI 本轮做了什么，建议短句，可空。
- `observations`：针对当前新消息提取的新记忆列表（0..N 条），可空；每条会独立改写与入库。
- 两字段都为空时，仅结束会话，不写认知队列。

### 后台史官流水线

```
pending/{job_id}.json
    │
    ▼ dequeue（原子 os.replace）
processing/{job_id}.json
    │
    ▼ LLM 绝对化改写（消灭代词/相对时间/相对地点；结合“当前消息原文 + 最近消息参考”做实体消歧）
    │
    ▼ 正则闸门检查
    │   通过 → is_absolute=true
    │   失败（重试 N 次后）→ 降级写入 is_absolute=false + warning
    │
    ▼ ChromaDB upsert（events collection）
    │
    ▼ 若有 observations → 可按 group/sender 等视角生成多条事件记录
    ▼ 若有 observations → tool_call 结构化提取 → 更新侧写文件 + 向量库
    │
    ▼ complete（删除 processing 文件）
        异常 → 重试次数 < job_max_retries？
                是 → requeue 回 pending（原子 os.replace）
                否 → failed/{job_id}.json
```

史官是独立的后台 `asyncio.Task`，不走主消息队列，不影响任何前台响应。默认单 worker，按需可扩展多 worker 并发消费。

### 史官参考上下文（新增）

`end` 入队时，系统会额外附带两类“仅供史官推理”的参考内容：

- `source_message`：触发本轮的当前消息原文（优先提取 `<content>`）。
- `recent_messages`：同会话最近若干条历史消息摘要（含时间、昵称、QQ号、文本片段）。

用途：

- 提升 `historian_rewrite` 的实体消歧能力（避免把第三方人物误写成当前 sender）。
- 提升 `historian_profile_merge` 的稳定性（冲突时更容易判断应跳过还是更新）。

这些字段用于后台推理，不会直接写入事件 metadata。

---

## 数据存储

### 事件记忆（ChromaDB events collection）

每条事件的 metadata 字段：

| 字段 | 说明 |
|------|------|
| `user_id` | 发送者 QQ 号 |
| `group_id` | 群号（私聊为空） |
| `sender_id` | 实际发送者 ID |
| `timestamp_utc` | UTC 时间（ISO 格式） |
| `timestamp_local` | 本地时间（Asia/Shanghai） |
| `timestamp_epoch` | UTC Unix 时间戳（秒，供时间范围过滤与衰减加权） |
| `request_type` | `group` 或 `private` |
| `perspective` | 记录视角（如 `group` / `sender` / `global`） |
| `is_absolute` | 是否通过绝对化闸门 |
| `schema_version` | 数据版本（`final_v1`） |

### 史官任务载荷中的参考字段（非 events metadata）

| 字段 | 说明 |
|------|------|
| `source_message` | 当前触发消息原文（截断后） |
| `recent_messages` | 最近消息参考列表（每条已裁剪） |
| `force` | 来自 `end.force` 的强制标记；为 `true` 时，史官在绝对化正则闸门失败且无实体 ID 漂移时可跳过闸门直接入库 |

### 检索排序策略（events）

事件检索采用两段式排序，兼顾语义相关性与时间新近性：

1. 语义召回（可选 rerank）得到候选集合；
2. 在候选集合上按时间衰减加权重排后再截断到 `top_k`。

加权公式：

```text
sim = clamp(1 - distance, 0, 1)
decay = 0.5 ^ (age_seconds / half_life_seconds)
final_score = sim × (1 + boost × decay)
```

- 仅当 `sim >= time_decay_min_similarity` 时才施加时间加权，防止“新但不相关”的结果上浮。
- `half_life_seconds = time_decay_half_life_days × 86400`。
- `time_from/time_to` 为硬过滤条件，先过滤再排序。

### 自动注入场景的 Query 构造

每轮对话自动注入认知记忆（`PromptBuilder -> cognitive.build_context`）时，检索 `query` 的构造规则如下：

1. 优先提取当前帧 `<message><content>...</content></message>` 的 `content` 作为查询文本；
2. 若无法提取（例如非 XML 纯文本），回退到原始 `question`；
3. 当 `content` 较短（当前实现阈值：`<= 20` 字）时，追加一行轻量语境（群/私聊、是否 `@`、发送者、群名）以缓解“这/那个”类指代查询的漏召回。

说明：

- 该规则影响自动注入路径下的语义召回与 rerank（两者使用同一 query）。
- 手动工具 `cognitive.search_events` / `cognitive.search_profiles` 仍使用调用方显式传入的 `query`。

### 用户/群侧写（Markdown + YAML Frontmatter）

文件路径：`data/cognitive/profiles/users/{user_id}.md` / `groups/{group_id}.md`

格式示例：

```markdown
---
entity_type: user
entity_id: "12345678"
name: Null
tags:
  - Python
  - 异步编程
  - QQ机器人
updated_at: "2026-02-22T10:30:00"
source_event_id: abc123_0_1740218400000
---
Null 是一名 Python 开发者，专注于异步架构设计。曾在 Python 群中多次讨论 asyncio 最佳实践，对 QQ 机器人开发有深入研究。
```

每次更新前自动备份到 `data/cognitive/profiles/history/{type}/{id}/{timestamp}.md`，默认保留最近 5 个版本。

### 文件队列三态

```
pending/    → 待处理（end 工具写入）
processing/ → 处理中（史官原子移动）
failed/     → 失败（自动清理，默认保留 30 天）
```

### 目录结构

```
data/cognitive/
├── chromadb/                    # ChromaDB 向量库持久化
├── profiles/
│   ├── users/{user_id}.md       # 用户侧写
│   ├── groups/{group_id}.md     # 群聊侧写
│   └── history/
│       ├── users/{user_id}/     # 用户侧写快照
│       └── groups/{group_id}/   # 群聊侧写快照
└── queues/
    ├── pending/                 # 待处理任务
    ├── processing/              # 处理中任务
    └── failed/                  # 失败任务
```

---

## 配置参考

### [cognitive] 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `true` | 是否启用（变更需重启；未配置 embedding 时会自动降级） |

### [cognitive.vector_store]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | str | `data/cognitive/chromadb` | ChromaDB 存储路径 |

### [cognitive.query]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `auto_top_k` | int | `3` | 每轮自动注入的相关事件条数（支持热更新） |
| `enable_rerank` | bool | `true` | 是否启用认知记忆检索重排（独立于 `knowledge.enable_rerank`，支持热更新） |
| `recent_end_summaries_inject_k` | int | `30` | 认知模式下额外注入最近 N 条 end 行动摘要（短期工作记忆，带时间；0=禁用，支持热更新） |
| `time_decay_enabled` | bool | `true` | 是否启用事件检索时间衰减加权（支持热更新） |
| `time_decay_half_life_days_auto` | float | `14.0` | 自动注入场景半衰期（天，支持热更新） |
| `time_decay_half_life_days_tool` | float | `60.0` | 工具检索场景半衰期（天，支持热更新） |
| `time_decay_boost` | float | `0.2` | 时间加权强度（支持热更新） |
| `time_decay_min_similarity` | float | `0.35` | 启用时间加权的最低语义相似度阈值（支持热更新） |
| `tool_default_top_k` | int | `12` | `cognitive.search_events` 默认返回条数（支持热更新） |
| `profile_top_k` | int | `8` | `cognitive.search_profiles` 默认返回条数（支持热更新） |
| `rerank_candidate_multiplier` | int | `3` | 重排候选倍数（必须 >= 2，否则跳过重排；候选数 = top_k × multiplier） |

### [models.historian]（可选）

史官后台改写使用的模型，未配置时回退到 `[models.agent]`。可指定轻量模型以降低成本。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_url` | str | 继承 agent | OpenAI 兼容 base URL |
| `api_key` | str | 继承 agent | API 密钥 |
| `model_name` | str | 继承 agent | 模型名称 |
| `max_tokens` | int | 继承 agent | 最大生成 tokens |

### [cognitive.historian]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rewrite_max_retry` | int | `2` | 绝对化改写最大重试次数（支持热更新） |
| `recent_messages_inject_k` | int | `12` | 提供给史官的最近消息参考条数（0=禁用，支持热更新） |
| `recent_message_line_max_len` | int | `240` | 最近消息参考中每条文本最大长度（支持热更新） |
| `source_message_max_len` | int | `800` | 当前消息原文最大长度（支持热更新） |
| `poll_interval_seconds` | float | `1.0` | 史官轮询间隔秒数（支持热更新） |
| `stale_job_timeout_seconds` | float | `300.0` | 启动时恢复 stale 任务的超时阈值 |

### [cognitive.profile]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | str | `data/cognitive/profiles` | 侧写文件存储路径 |
| `revision_keep` | int | `5` | 每实体保留的快照版本数 |

### [cognitive.queue]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | str | `data/cognitive/queues` | 队列文件存储路径 |
| `failed_max_age_days` | int | `30` | failed 队列文件最大保留天数 |
| `failed_max_files` | int | `500` | failed 队列最大文件数 |
| `failed_cleanup_interval` | int | `100` | 每 N 轮 poll 执行一次清理（0 禁用） |
| `job_max_retries` | int | `3` | 单个任务最大自动重试次数（超过后移入 failed，0=不重试） |

### [models.embedding]（必须配置）

复用知识库的 embedding 配置，无需重复配置：

| 字段 | 说明 |
|------|------|
| `api_url` | OpenAI 兼容 base URL |
| `api_key` | API 密钥 |
| `model_name` | 模型名称（推荐 `text-embedding-3-small`） |
| `dimensions` | 向量维度（可选，模型默认值） |

### 热更新说明

- **支持热更新**：`cognitive.query.*`、`cognitive.historian.poll_interval_seconds`、`cognitive.historian.rewrite_max_retry`、`cognitive.historian.recent_messages_inject_k`、`cognitive.historian.recent_message_line_max_len`、`cognitive.historian.source_message_max_len`
- **需重启**：`cognitive.enabled`、`models.embedding.*`、`models.rerank.*`

说明：
- `knowledge.enable_rerank` 仅控制知识库检索重排。
- 认知记忆重排由 `cognitive.query.enable_rerank` 独立控制。

---

## AI 工具

认知记忆系统向 AI 暴露 3 个主动工具（toolset 前缀 `cognitive.`）：

### cognitive.search_events

搜索历史事件记忆，用于回忆之前发生过的事情（支持时间范围硬过滤 + 时间衰减加权排序）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词或语义描述 |
| `target_user_id` | string | 否 | 限定用户 ID |
| `target_group_id` | string | 否 | 限定群 ID |
| `top_k` | integer | 否 | 返回条数（默认使用 `cognitive.query.tool_default_top_k`） |
| `time_from` | string | 否 | 起始时间（ISO 格式） |
| `time_to` | string | 否 | 截止时间（ISO 格式） |

说明：

- `time_from` / `time_to` 生效于服务端 where 过滤（非 prompt 层软约束）。
- 当 `time_from > time_to` 时，系统会自动交换并记录 warning 日志，避免空结果误用。

### cognitive.get_profile

获取指定用户或群聊的侧写信息。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entity_type` | string | 是 | `user` 或 `group` |
| `entity_id` | string | 是 | 用户 ID 或群 ID |

### cognitive.search_profiles

语义搜索用户/群聊侧写，用于查找具有特定特征的用户或群。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词 |
| `entity_type` | string | 否 | 限定类型：`user` 或 `group` |
| `top_k` | integer | 否 | 返回条数（默认 8） |

---

## 运维

### 回退方式

**级别 1：重启回退**（推荐，最安全）

```toml
# config.toml
[cognitive]
enabled = false
```

重启后：PromptBuilder 回退到旧 end_summaries 注入，end 工具只走旧路径，cognitive 工具返回"未启用"。`pending/` 中未消费的任务保留，下次重新启用时继续处理。

**级别 2：侧写回滚**

若某用户侧写被错误更新，从快照目录恢复：

```bash
# 查看快照列表
ls data/cognitive/profiles/history/users/{user_id}/

# 覆盖回正确版本
cp data/cognitive/profiles/history/users/{user_id}/{timestamp}.md \
   data/cognitive/profiles/users/{user_id}.md
```

**级别 3：完整移除**

```bash
# 1. 设置 cognitive.enabled = false 并重启
# 2. 删除数据目录（可选）
rm -rf data/cognitive/
```

旧 `end_summaries.json` 在整个过渡期保持双写，不会丢失任何数据。

### failed 队列排查

```bash
# 查看失败任务
ls data/cognitive/queues/failed/

# 查看某个失败任务的内容和错误信息
cat data/cognitive/queues/failed/{job_id}.json
```

failed 文件中包含原始 job 数据和 `error` 字段，记录失败原因。

### 日志关键字

| 关键字 | 含义 |
|--------|------|
| `[认知记忆]` | 启动/降级相关 |
| `HistorianWorker` | 史官任务处理 |
| `historian_rewrite` | 绝对化改写 |
| `historian_profile_merge` | 侧写合并 |
| `闸门` / `is_absolute=false` | 正则闸门降级写入 |
| `cognitive` | 工具调用相关 |

---

## FAQ

**Q: 开启后旧的 end_summaries 还能用吗？**

可以。end 工具采用双写策略，同时写旧 `end_summaries.json` 和新 cognitive 队列。随时设置 `cognitive.enabled = false` 重启即可完整回退，不丢任何数据。

**Q: 跨群会不会串记忆？**

不会。ChromaDB 查询时通过 `where` 参数硬过滤 `group_id`（群聊）或 `user_id`（私聊），跨群误召回 = 0，不依赖向量相似度。

**Q: embedding 模型怎么选？**

推荐 `text-embedding-3-small`（OpenAI），性价比高，兼容 OpenAI API 格式。也可使用任何 OpenAI 兼容的 embedding 服务（如 Jina、本地 Ollama 等）。

**Q: 认知记忆和知识库能同时用吗？**

可以，且推荐同时使用。两者共享同一个 `Embedder` 实例（`[models.embedding]` 配置），不会重复创建连接。

**Q: 正则闸门误伤了合法内容怎么办？**

降级写入策略确保数据不丢失——即使闸门判定违规，事件仍会写入 ChromaDB，只是 metadata 中标记 `is_absolute=false`。这类事件仍可被语义检索到，只是绝对化质量略低。

**Q: 史官处理速度跟不上怎么办？**

默认是单 worker 串行处理，每个任务需要 1-2 次 LLM 调用。高并发场景下 `pending/` 目录会积压，但不影响前台响应。可适当降低 `poll_interval_seconds` 或扩展多 worker 加快消费速度。
