# Undefined 认知记忆架构重设计方案（Claude 最终版）

版本：2026-02-21

---

## 1. 对 Gemini 初稿和 GPT 方案的评审

### 1.1 三方共识（无争议）

- "前台快 + 后台史官"解耦架构
- end_summary 拆分为"做了什么" + "获取到的新信息"
- 后台绝对化处理（消灭代词/相对时间/相对地点）
- 向量数据库存事件，metadata 过滤防串群
- 双轨查询：自动小 top_k + 工具大 top_k
- 侧写与事件记忆物理隔离

### 1.2 对 GPT 方案的辩驳

**同意并采纳的点**：
- 质量闸门（LLM 改写 + 规则校验兜底）——Gemini 和我的初版都缺这个
- 幂等 upsert（doc_id 去重）——工程上必要
- 时间范围过滤（time_from/time_to）——search_events 应支持

**反对的点**：

1. **侧写置信度系统过度工程**
   - GPT 提出 `confidence: 0.86`、`status: deprecated`、`source_event_ids` 追溯
   - 问题：这是一个 QQ 机器人，不是知识图谱系统。置信度由谁打分？LLM 打分不稳定，规则打分覆盖不全。维护 deprecated 历史增加存储和查询复杂度，收益极低
   - **我的立场**：侧写就是"当前最新状态"，新信息直接覆盖旧信息，简单粗暴但有效。如果 LLM 误判，下次对话自然会纠正

2. **profile_state.json + profile_view.md 双文件**
   - GPT 认为"不要只存 Markdown"，要结构化 JSON 作为源数据
   - 问题：两份文件需要保持同步，增加维护成本。结构化 JSON 的 `facts` 数组需要 LLM 精确输出 JSON schema，容易出格式错误
   - **我的立场**：只存一份结构化 JSON（含 summary 自然语言字段），注入时直接用 summary 字段。不需要额外的 Markdown 视图文件

3. **SQLite 的引入**
   - GPT 提到 "SQLite + Chroma/LanceDB"
   - 问题：ChromaDB 自带持久化，不需要额外的 SQLite。引入 SQLite 增加了一层不必要的抽象
   - **我的立场**：只用 ChromaDB，它已经覆盖了向量存储 + metadata 过滤的全部需求

4. **DLQ（死信队列）和 Redis Streams**
   - GPT 提到"失败任务指数退避重试，超过阈值进入 DLQ"，"将来扩展到 Redis Streams"
   - 问题：单机 QQ 机器人，asyncio.Queue 足够。DLQ 概念在这个规模下是过度设计
   - **我的立场**：失败任务写入 fallback JSON 文件，下次启动时重试。够用

5. **侧写 chunk embedding**
   - GPT 提出把 profile 按 section chunk 化（200-400 tokens），每段 embedding 后入 profile_chunks 集合
   - 问题：用户侧写通常 200-500 字，群聊侧写类似。这个长度根本不需要 chunk。全文注入 + 全文 embedding 就够了
   - **我的立场**：侧写直接全文注入。只有当侧写超过阈值（比如 2000 字）时才考虑截断，但这种情况极少发生

6. **验收指标过于理想化**
   - "去代词通过率 > 98%"、"史官成功率 > 99%"
   - 问题：这些指标怎么测量？谁来标注？对于一个 QQ 机器人项目，这种量化验收不现实
   - **我的立场**：验收标准应该是功能性的（能跑、能查、不串群），不是统计性的

---

## 2. 技术选型

### 2.1 向量数据库：ChromaDB

| 维度 | ChromaDB | LanceDB | sqlite-vec | Qdrant(local) | FAISS |
|------|----------|---------|------------|---------------|-------|
| 嵌入式 | ✅ | ✅ | ✅ | ✅ | ✅ |
| metadata 过滤 | ✅ 强（$and/$or） | ✅ SQL-like | ⚠️ 弱 | ✅ 强 | ❌ 无 |
| 持久化 | ✅ 目录级 | ✅ 文件级 | ✅ SQLite | ✅ 目录级 | ⚠️ 需手动 |
| Python 原生 | ✅ | ✅ | ⚠️ C扩展 | ⚠️ Rust绑定 | ⚠️ C++绑定 |
| uv 安装 | ✅ 简单 | ✅ 简单 | ⚠️ 编译 | ⚠️ 较重 | ⚠️ 编译 |
| upsert 支持 | ✅ | ✅ | ❌ | ✅ | ❌ |

**选择 ChromaDB**：metadata 过滤能力强、upsert 原生支持、安装简单、与 langchain 集成好。

### 2.2 Embedding：OpenAI 兼容 API

复用项目已有的 `openai` 依赖，通过配置指向任意 OpenAI 兼容端点：
- 默认：`text-embedding-3-small`（1536 维，$0.02/1M tokens）
- 可配置切换到自托管模型或其他 API

**不用本地模型的理由**：sentence-transformers 需要 PyTorch（~2GB），对 QQ 机器人太重。

### 2.3 新增依赖

```toml
"chromadb>=1.0.0",
```

仅此一个。embedding 复用已有 `openai` 包。

---

## 3. 数据模型

### 3.1 end 工具参数改造

```json
{
    "type": "function",
    "function": {
        "name": "end",
        "parameters": {
            "properties": {
                "action_summary": {
                    "type": "string",
                    "description": "这次做了什么（具体行为和结果）"
                },
                "new_info": {
                    "type": "string",
                    "description": "从会话中获取到的新信息（关于用户、群聊、技术等的持久性信息）"
                },
                "force": { "type": "boolean" }
            }
        }
    }
}
```

与 GPT 方案的 `did_what/new_info` 本质相同，命名风格统一为 snake_case。

### 3.2 事件记忆（ChromaDB collection: `events`）

```
Document:  绝对化后的文本（action_summary + new_info 合并提纯）
Embedding: 文本向量
ID:        "{request_id}" （天然幂等键，无需额外设计）
Metadata:
  timestamp: str        # ISO 时间戳
  user_id: int          # 交互对象 QQ 号
  user_name: str        # 交互对象名称
  group_id: int | None  # 群号（私聊为 None）
  group_name: str | None
  request_type: str     # "private" | "group"
```

**与 GPT 方案的差异**：
- 不需要 `schema_version`——数据结构简单，版本迁移直接代码处理
- 不需要 `message_ids` 追溯——QQ 消息 ID 不持久，追溯价值低
- 不需要 `timezone/location_text`——QQ 机器人场景下地点信息通常不可用，硬塞"未知地点"是噪声
- 用 `request_id` 作为 doc_id，天然幂等，不需要额外的 `idempotency_key`

### 3.3 用户侧写（`data/profiles/users/{user_id}.json`）

```json
{
    "user_id": 1708213363,
    "display_name": "Null",
    "updated_at": "2026-02-21T11:08:00+08:00",
    "summary": "Null 是 Undefined 项目的作者，全栈开发者，主要使用 Python 和 TypeScript。偏好简洁代码，不喜欢过度工程。位于台湾。",
    "traits": {
        "technical": ["Python", "TypeScript", "异步编程"],
        "personality": ["直接", "技术导向"],
        "preferences": ["简洁代码", "奥卡姆剃刀"],
        "location": "Taiwan",
        "role": "Undefined 项目作者"
    }
}
```

### 3.4 群聊侧写（`data/profiles/groups/{group_id}.json`）

```json
{
    "group_id": 1017148870,
    "group_name": "Undefined 测试群",
    "updated_at": "2026-02-21T11:08:00+08:00",
    "summary": "Undefined 机器人的开发测试群，主要讨论 Python、QQ 机器人开发和 AI 相关话题。氛围轻松，技术讨论为主。",
    "traits": {
        "purpose": "开发测试",
        "topics": ["Python", "QQ机器人", "AI"],
        "culture": ["技术讨论为主", "氛围轻松"],
        "rules": []
    }
}
```

**设计决策**：
- 单文件 JSON，不搞双文件（反对 GPT 的 state.json + view.md）
- `summary` 是自然语言，直接注入 prompt；`traits` 是结构化数据，供程序过滤
- 无置信度——新信息直接覆盖，LLM 负责判断是否该覆盖
- 侧写的 `summary` 字段做 embedding 存入 ChromaDB 独立 collection `profiles`，支持语义搜索"谁是做什么的"

---

## 4. 后台史官进程

### 4.1 触发机制

```
end 工具 handler.py
  ↓ 构建 memory_job dict
  ↓ asyncio.create_task(historian.process(job))
  ↓ task 加入 AIClient._background_tasks 防 GC
主对话立即返回，不等待
```

### 4.2 史官工作流

```
Step 1: 接收 memory_job
  ├─ action_summary, new_info
  ├─ user_id, user_name, group_id, group_name
  ├─ request_id, timestamp, request_type
  └─ recent_messages（最近几条原始消息，用于侧写提取）

Step 2: LLM 绝对化提纯
  ├─ 输入：action_summary + new_info + 上下文元数据
  ├─ 输出：绝对视角的 canonical_text
  └─ 使用配置的史官模型（默认复用 chat 模型）

Step 3: 质量闸门（采纳 GPT 建议）
  ├─ 规则校验：检查是否残留代词/相对时间/相对地点
  ├─ 词表：["我", "你", "他", "她", "今天", "昨天", "刚才", "这里", "那边", ...]
  ├─ 如果残留 → 回炉重写一次（附带具体指出残留词）
  └─ 二次仍失败 → 降级存储原始文本，日志告警

Step 4: Embedding + 存入 ChromaDB
  ├─ 调用 embedding API 获取向量
  └─ chromadb.upsert(id=request_id, document=canonical_text, embedding=vec, metadata=ctx)

Step 5: 侧写更新（仅当 new_info 非空时）
  ├─ 读取旧侧写 JSON
  ├─ 连同 new_info + recent_messages 发给 LLM
  ├─ LLM 输出更新后的 JSON
  ├─ 原子写入文件
  └─ 更新 profiles collection 中的 embedding
```

### 4.3 史官 Prompt

**绝对化提纯 Prompt**：
```
你是一个旁观者（史官）。请将以下摘要改写为绝对视角。
当前时间：{timestamp}
交互对象：{user_name}({user_id})
场景：{scene_desc}

铁律：
- 消灭所有人称代词（我/你/他），用具体名字替换
- 消灭所有相对时间（今天/刚才），用具体日期时间替换
- 消灭所有相对地点（这里），用具体地点替换
- 合并为一两句话，保持简洁

原始摘要：
行为：{action_summary}
新信息：{new_info}
```

**侧写更新 Prompt**：
```
根据新信息更新侧写。输出完整 JSON。

旧侧写：{old_profile_json}
新信息：{new_info}

规则：
- 提取长期静态特征（技术栈、职业、性格、偏好等）
- 冲突信息用新的覆盖旧的
- 忽略临时性信息（心情、正在吃饭等）
- 忽略明显的玩笑或反讽
- summary 字段用自然语言概括此人/此群的全貌
```

### 4.4 错误处理

| 失败点 | 处理策略 |
|--------|---------|
| LLM 调用失败 | 降级存储原始文本（不提纯），日志告警 |
| Embedding 失败 | 写入 `data/cognitive_backlog.json`，下次启动重试 |
| ChromaDB 写入失败 | 同上 |
| 侧写更新 LLM 输出格式错误 | 跳过本次侧写更新，仅存事件记忆 |
| 并发冲突 | asyncio.Lock 保护侧写文件写入 |

---

## 5. 双轨查询机制

### 5.1 自动查询（潜意识注入）

在 `prompts.py` 的 `build_messages()` 中，替换现有的全量注入：

```python
# 1. 读取当前用户侧写（文件读取，极快）
user_profile = await profile_storage.get_user(user_id)

# 2. 群聊场景：读取群聊侧写
group_profile = await profile_storage.get_group(group_id) if group_id else None

# 3. 向量查询相关事件（top_k=3）
#    用用户最新消息做 embedding 查询
#    硬过滤：群聊按 group_id，私聊按 user_id
relevant_events = await vector_store.query(
    text=user_message,
    top_k=config.cognitive.query.auto_top_k,  # 默认 3
    where={"group_id": group_id} if group_id else {"user_id": user_id}
)

# 4. 注入为 system message
```

**注入格式**：
```
【记忆系统】
[用户侧写] {user_profile.summary}
[群聊背景] {group_profile.summary}
[相关回忆]
- [2026-02-20] {event_1}
- [2026-02-19] {event_2}
- [2026-02-18] {event_3}
```

### 5.2 主动查询（AI 工具调用）

新增 toolset `cognitive/`，两个工具：

**cognitive.search_events**：
```json
{
    "name": "search_events",
    "description": "搜索过去发生的事件记忆。当需要回想具体经过、查找历史记录时调用。",
    "parameters": {
        "properties": {
            "query": { "type": "string", "description": "搜索关键词" },
            "target_user_id": { "type": "integer", "description": "限定某个用户（可选）" },
            "target_group_id": { "type": "integer", "description": "限定某个群聊（可选）" },
            "top_k": { "type": "integer", "description": "返回条数，默认10" },
            "time_from": { "type": "string", "description": "起始时间，ISO格式（可选）" },
            "time_to": { "type": "string", "description": "截止时间，ISO格式（可选）" }
        },
        "required": ["query"]
    }
}
```

**cognitive.get_profile**：
```json
{
    "name": "get_profile",
    "description": "查询用户或群聊的侧写。当需要了解某人背景、技术栈、偏好，或某群的主题和文化时调用。",
    "parameters": {
        "properties": {
            "target_id": { "type": "integer", "description": "QQ号或群号" },
            "target_type": { "type": "string", "enum": ["user", "group"] }
        },
        "required": ["target_id", "target_type"]
    }
}
```

**返回格式**：search_events 返回按相关度排序的事件列表（含时间戳和文本）；get_profile 返回完整侧写 JSON。

---

## 6. 新增模块与文件结构

```
src/Undefined/
├── cognitive/                          # 新增：认知记忆核心模块
│   ├── __init__.py
│   ├── vector_store.py                 # ChromaDB 封装（query/upsert/delete）
│   ├── embedding.py                    # Embedding API 封装（OpenAI 兼容）
│   ├── historian.py                    # 后台史官（提纯+嵌入+侧写更新）
│   └── profile_storage.py             # 侧写文件 CRUD
├── skills/toolsets/cognitive/          # 新增：认知查询工具集
│   ├── search_events/
│   │   ├── config.json
│   │   └── handler.py
│   └── get_profile/
│       ├── config.json
│       └── handler.py
data/
├── chromadb/                           # ChromaDB 持久化目录
├── profiles/
│   ├── users/                          # 用户侧写 JSON
│   └── groups/                         # 群聊侧写 JSON
└── cognitive_backlog.json              # 失败任务备份（启动时重试）
```

---

## 7. 现有代码改造清单

| 文件 | 改造内容 |
|------|---------|
| `skills/tools/end/config.json` | `summary` → `action_summary` + `new_info` 双字段 |
| `skills/tools/end/handler.py` | 构建 memory_job，触发 `historian.process()` 后台任务 |
| `ai/prompts.py` | 替换全量注入（207-263行）为向量查询 + 侧写注入 |
| `ai/client.py` | 初始化 cognitive 模块（vector_store, embedding, historian, profile_storage），注入到 tool context |
| `end_summary_storage.py` | 保留，作为向量数据库不可用时的 fallback |
| `memory.py` | 保留现有功能不变（AI 主动记忆是独立功能） |
| `pyproject.toml` | 新增 `chromadb>=1.0.0` |
| `res/prompts/undefined.xml` | 更新记忆系统说明、end_summary 指导、工具使用说明 |

---

## 8. 配置项设计

```toml
[cognitive]
enabled = true                              # 总开关（关闭则回退到旧的全量注入）

[cognitive.embedding]
api_url = ""                                # 留空则复用 chat 模型的 api_url
api_key = ""                                # 留空则复用 chat 模型的 api_key
model = "text-embedding-3-small"

[cognitive.vector_store]
path = "data/chromadb"                      # 持久化路径

[cognitive.query]
auto_top_k = 3                              # 自动注入的 top_k
tool_default_top_k = 10                     # 工具调用的默认 top_k

[cognitive.historian]
model_name = ""                             # 留空则复用 chat 模型
api_url = ""
api_key = ""
```

所有配置项均支持热更新，无需重启。`cognitive.vector_store.path` 除外（需重启）。

---

## 9. System Prompt 改造

在 `undefined.xml` 中替换现有的 `<memory_management>` 和 `<end_summary_guidelines>`：

```xml
<cognitive_memory priority="P0">
  **记忆系统**：
  1) 系统已自动注入【用户侧写】【群聊背景】【相关回忆】，优先使用这些信息自然对话。
  2) 如果自动注入的回忆不足以回答，主动调用 search_events 深度搜索。
  3) 如果需要了解不在场的用户或群聊，调用 get_profile。

  **end 工具填写原则**：
  - action_summary：这次做了什么（具体行为和结果）
  - new_info：获取到的新的持久性信息（技术栈、偏好、身份等）
  - 临时性信息（心情、正在吃饭）不要写入 new_info
</cognitive_memory>
```

---

## 10. 数据迁移

启动时自动检测：
1. `data/end_summaries.json` 存在且 ChromaDB `events` collection 为空 → 批量迁移
2. 迁移流程：逐条读取 → embedding → upsert（后台异步，不阻塞启动）
3. 原文件保留作为备份
4. `memory.py` 长期记忆保持不变——它是独立的 AI 主动记忆功能

---

## 11. 验证方案

1. **功能验证**：启动机器人 → 对话几轮 → 调用 end → 检查 `data/chromadb/` 有数据、`data/profiles/` 有侧写
2. **查询验证**：新对话中检查自动注入的记忆是否相关；调用 search_events 和 get_profile 验证主动查询
3. **隔离验证**：群A的记忆不会出现在群B的自动注入中
4. **降级验证**：关闭 `cognitive.enabled` 后回退到旧的全量注入，不影响正常使用
5. **迁移验证**：旧 end_summaries.json 数据能被正确迁移到 ChromaDB

---

## 12. Claude vs GPT 最终决策总结

| 决策点 | Claude 立场 | GPT 立场 | 最终建议 |
|--------|------------|----------|---------|
| 向量数据库 | ChromaDB 单一方案 | SQLite + Chroma/LanceDB | **ChromaDB 即可**，不需要 SQLite |
| 侧写存储 | 单文件 JSON（含 summary + traits） | 双文件（state.json + view.md） | **单文件 JSON**，简单够用 |
| 侧写置信度 | 不需要，直接覆盖 | 需要 confidence + deprecated | **不需要**，过度工程 |
| 侧写 chunk | 不需要，全文注入 | 需要按段 chunk embedding | **不需要**，侧写不会太长 |
| 失败处理 | fallback JSON + 启动重试 | DLQ + 指数退避 | **fallback JSON**，单机够用 |
| 质量闸门 | 采纳 GPT 建议 | LLM + 规则校验 | **采纳**，这是好建议 |
| 时间范围过滤 | 采纳 GPT 建议 | search_events 支持 time_from/to | **采纳** |
| 幂等键 | request_id 天然幂等 | 额外 idempotency_key | **用 request_id**，不需要额外字段 |
| Embedding | OpenAI API（复用已有依赖） | 未明确 | **OpenAI 兼容 API** |

**核心原则**：奥卡姆剃刀。能用一个组件解决的不用两个，能用文件解决的不上数据库，能用 asyncio 解决的不上消息队列。

---

## 13. 对 Gemini 裁决的回应（v2 补充）

### 13.1 侧写格式：Markdown+YAML vs JSON

Gemini 提出用 Markdown + YAML Frontmatter（复用 Anthropic Skills 的 SKILL.md 模式）。

**Gemini 的理由**：JSON 转义字符浪费 token，Markdown 对 LLM 更友好。

**我的回应**：
- 我的 JSON 设计中，注入 prompt 时**只注入 `summary` 字段**（纯自然语言），LLM 永远不会看到 JSON 结构
- JSON 的 `traits` 字段是给程序用的（过滤、搜索），不是给 LLM 读的
- YAML 缩进敏感，LLM 输出 YAML 比输出 JSON 更容易出格式错误
- 项目的 SKILL.md 解析器是为 Anthropic Skills 定制的，复用需要改造

**最终决定**：保持 JSON 存储。但如果你更喜欢 Gemini 的 Markdown 格式，切换成本很低——只需改 `profile_storage.py` 的读写逻辑。
