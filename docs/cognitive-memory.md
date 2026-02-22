# 认知记忆系统

## 概述

认知记忆系统是 Undefined 的长期记忆架构，由两部分组成：

- **事件记忆**：每轮对话结束时，AI 将本轮摘要写入文件队列，后台史官异步改写为绝对化事件并存入 ChromaDB 向量库，支持语义检索。
- **用户/群侧写**：当对话中出现新信息（偏好、身份、习惯等）时，史官自动合并更新 Markdown 侧写文件，下次对话时注入 prompt。

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

### 后台史官流水线

```
pending/{job_id}.json
    │
    ▼ dequeue（原子 os.replace）
processing/{job_id}.json
    │
    ▼ LLM 绝对化改写（消灭代词/相对时间/相对地点）
    │
    ▼ 正则闸门检查
    │   通过 → is_absolute=true
    │   失败（重试 N 次后）→ 降级写入 is_absolute=false + warning
    │
    ▼ ChromaDB upsert（events collection）
    │
    ▼ 若有 new_info → tool_call 结构化提取 → 更新侧写文件 + 向量库
    │
    ▼ complete（删除 processing 文件）
        异常 → failed/{job_id}.json
```

史官是独立的后台 `asyncio.Task`，不走主消息队列，不影响任何前台响应。

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
| `request_type` | `group` 或 `private` |
| `is_absolute` | 是否通过绝对化闸门 |
| `schema_version` | 数据版本（`final_v1`） |

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
| `enabled` | bool | `true` | 是否启用（变更需重启） |

### [cognitive.vector_store]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | str | `data/cognitive/chromadb` | ChromaDB 存储路径 |

### [cognitive.query]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `auto_top_k` | int | `3` | 每轮自动注入的相关事件条数（支持热更新） |
| `tool_default_top_k` | int | `12` | `cognitive.search_events` 默认返回条数（支持热更新） |
| `profile_top_k` | int | `8` | `cognitive.search_profiles` 默认返回条数（支持热更新） |
| `rerank_candidate_multiplier` | int | `3` | 重排候选倍数（启用 rerank 时生效） |

### [cognitive.historian]

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rewrite_max_retry` | int | `2` | 绝对化改写最大重试次数（支持热更新） |
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

### [models.embedding]（必须配置）

复用知识库的 embedding 配置，无需重复配置：

| 字段 | 说明 |
|------|------|
| `api_url` | OpenAI 兼容 base URL |
| `api_key` | API 密钥 |
| `model_name` | 模型名称（推荐 `text-embedding-3-small`） |
| `dimensions` | 向量维度（可选，模型默认值） |

### 热更新说明

- **支持热更新**：`cognitive.query.*`、`cognitive.historian.poll_interval_seconds`、`cognitive.historian.rewrite_max_retry`
- **需重启**：`cognitive.enabled`、`models.embedding.*`、`models.rerank.*`

---

## AI 工具

认知记忆系统向 AI 暴露 3 个主动工具（toolset 前缀 `cognitive.`）：

### cognitive.search_events

搜索历史事件记忆，用于回忆之前发生过的事情。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 搜索关键词或语义描述 |
| `target_user_id` | string | 否 | 限定用户 ID |
| `target_group_id` | string | 否 | 限定群 ID |
| `top_k` | integer | 否 | 返回条数（默认 12） |
| `time_from` | string | 否 | 起始时间（ISO 格式） |
| `time_to` | string | 否 | 截止时间（ISO 格式） |

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

史官是单 worker 串行处理，每个任务需要 1-2 次 LLM 调用。高并发场景下 `pending/` 目录会积压，但不影响前台响应。可适当降低 `poll_interval_seconds` 加快消费速度。
