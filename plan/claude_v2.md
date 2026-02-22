# Undefined 认知记忆架构 — 最终统一方案 v2

版本：2026-02-21 | 综合 Claude / GPT / Gemini 三方研讨

---

## 0. 三方共识（无争议直接采纳）

- 前台快 + 后台史官解耦
- end_summary 拆分为 `action_summary`（做了什么）+ `new_info`（新信息）
- 后台绝对化：消灭代词、相对时间、相对地点
- 向量数据库存事件，metadata 过滤防串群
- 双轨查询：自动小 top_k + 工具大 top_k
- 侧写与事件记忆物理隔离
- 质量闸门：LLM 提纯 + 正则校验兜底（GPT 提出，三方一致同意）
- 幂等：用 `request_id` 作为 doc_id，天然去重

---

## 1. 争议裁决

| 争议点 | GPT | Claude | Gemini | 最终裁决 |
|--------|-----|--------|--------|---------|
| 向量数据库 | SQLite + Chroma | ChromaDB 单一 | ChromaDB 单一 | **ChromaDB**（2:1） |
| 侧写格式 | state.json + view.md | 单文件 JSON | Markdown + YAML | **JSON**（见下方论证） |
| 侧写置信度 | confidence + deprecated | 不需要，直接覆盖 | 不需要，暴力覆盖 | **不需要**（2:1） |
| 侧写 chunk | 按段 chunk embedding | 不需要，全文注入 | 全文 embedding | **不需要 chunk**（2:1） |
| 失败处理 | DLQ + 指数退避 | fallback JSON | 未详述 | **fallback JSON**，单机够用 |
| 质量闸门 | LLM + 正则校验 | 采纳 GPT | 采纳 GPT | **LLM + 正则**（3:0） |
| 时间范围过滤 | search_events 支持 | 采纳 GPT | 采纳 GPT | **支持**（3:0） |

### 侧写格式论证

Gemini 提出 Markdown + YAML Frontmatter，理由是"JSON 转义浪费 token"。但：
- 注入 prompt 时只用 `summary` 字段（纯自然语言），LLM 不读 JSON 结构
- `traits` 是给程序过滤用的，不注入 prompt
- YAML 缩进敏感，LLM 输出更易出错
- JSON 解析更可靠（`json.loads` vs YAML parser）

如果后续想切换到 Markdown 格式，只需改 `profile_storage.py`，成本极低。

---

## 2. 技术选型

- **向量数据库**：ChromaDB（嵌入式，metadata 过滤强，upsert 原生，uv 安装简单）
- **Embedding**：OpenAI 兼容 API（复用已有 `openai` 依赖，默认 `text-embedding-3-small`）
- **新增依赖**：仅 `chromadb>=1.0.0`

---

## 3. 数据模型

### 3.1 end 工具参数

```json
{
    "name": "end",
    "parameters": {
        "properties": {
            "action_summary": {
                "type": "string",
                "description": "这次做了什么（具体行为和结果）"
            },
            "new_info": {
                "type": "string",
                "description": "从会话中获取到的新持久性信息（关于用户、群聊、技术等）"
            },
            "force": { "type": "boolean" }
        }
    }
}
```

### 3.2 事件记忆（ChromaDB collection: `events`）

| 字段 | 内容 |
|------|------|
| ID | `request_id`（天然幂等） |
| Document | 绝对化后的 canonical_text |
| Embedding | Document 的向量 |
| Metadata | `timestamp`, `user_id`, `user_name`, `group_id`, `group_name`, `request_type` |

### 3.3 用户侧写（`data/profiles/users/{user_id}.json`）

```json
{
    "user_id": 1708213363,
    "display_name": "Null",
    "updated_at": "2026-02-21T11:08:00+08:00",
    "summary": "Null 是 Undefined 项目的作者，全栈开发者，主要使用 Python 和 TypeScript。偏好简洁代码，位于台湾。",
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
    "summary": "Undefined 机器人的开发测试群，主要讨论 Python、QQ 机器人和 AI。",
    "traits": {
        "purpose": "开发测试",
        "topics": ["Python", "QQ机器人", "AI"],
        "culture": ["技术讨论为主", "氛围轻松"],
        "rules": []
    }
}
```

- `summary`：自然语言，注入 prompt 用
- `traits`：结构化数据，程序过滤用，不注入 prompt
- 侧写 `summary` 做 embedding 存入 ChromaDB `profiles` collection

---

## 4. 后台史官进程

### 触发

```
end handler → 构建 memory_job → asyncio.create_task(historian.process(job))
task 加入 AIClient._background_tasks 防 GC，主对话立即返回
```

### 工作流

```
Step 1: 接收 memory_job（action_summary, new_info, 上下文元数据, recent_messages）

Step 2: LLM 绝对化提纯
  → 输入：原始摘要 + 时间/人物/场景元数据
  → 输出：绝对视角 canonical_text

Step 3: 质量闸门
  → 正则检查残留代词/相对词：["我","你","他","她","今天","昨天","刚才","这里","那边"]
  → 命中 → 回炉重写一次（指出具体残留词）
  → 二次失败 → 降级存原始文本，日志告警

Step 4: Embedding → ChromaDB upsert（id=request_id）

Step 5: 侧写更新（仅 new_info 非空时）
  → 读旧侧写 → LLM 合并 → 原子写入文件 → 更新 profiles collection
```

### 史官 Prompt

**绝对化**：
```
你是旁观者（史官）。将以下摘要改写为绝对视角。
当前时间：{timestamp}  交互对象：{user_name}({user_id})  场景：{scene}

铁律：消灭代词（我/你/他）→具体名字，相对时间→具体日期，相对地点→具体地点。一两句话。

行为：{action_summary}
新信息：{new_info}
```

**侧写合并**：
```
根据新信息更新侧写，输出完整 JSON。
旧侧写：{old_json}  新信息：{new_info}
规则：提取长期特征，冲突用新覆旧，忽略临时信息和玩笑。
```

### 错误处理

| 失败点 | 策略 |
|--------|------|
| LLM 失败 | 降级存原始文本 |
| Embedding 失败 | 写入 `data/cognitive_backlog.json`，启动时重试 |
| ChromaDB 失败 | 同上 |
| 侧写 JSON 格式错误 | 跳过侧写更新，仅存事件 |
| 并发冲突 | asyncio.Lock 保护侧写写入 |

---

## 5. 双轨查询

### 自动注入（每次发车前，在 `prompts.py` 的 `build_messages()` 中）

1. 读当前 user/group 侧写文件（极快）
2. 用用户最新消息做 embedding，查 ChromaDB `top_k=3`，硬过滤 `group_id`/`user_id`
3. 注入格式：

```xml
<cognitive_context>
  <user_profile>{user_profile.summary}</user_profile>
  <group_profile>{group_profile.summary}</group_profile>
  <relevant_events>
    - [2026-02-20] Undefined 为 Null 修复了并发 Bug。
    - [2026-02-18] Null 提出要引入 ChromaDB。
  </relevant_events>
</cognitive_context>
```

### 主动查询（AI 工具调用）

新增 `skills/toolsets/cognitive/` 工具集：

**cognitive.search_events**：`query`(必填), `target_user_id`, `target_group_id`, `top_k`(默认10), `time_from`, `time_to`

**cognitive.get_profile**：`target_id`(必填), `target_type`("user"/"group", 必填)

---

## 6. 文件结构

```
src/Undefined/
├── cognitive/                     # 新增
│   ├── __init__.py
│   ├── vector_store.py            # ChromaDB 封装
│   ├── embedding.py               # Embedding API 封装
│   ├── historian.py               # 后台史官
│   └── profile_storage.py         # 侧写 CRUD
├── skills/toolsets/cognitive/     # 新增
│   ├── search_events/
│   │   ├── config.json
│   │   └── handler.py
│   └── get_profile/
│       ├── config.json
│       └── handler.py
data/
├── chromadb/                      # ChromaDB 持久化
├── profiles/users/                # 用户侧写
├── profiles/groups/               # 群聊侧写
└── cognitive_backlog.json         # 失败任务备份
```

---

## 7. 现有代码改造

| 文件 | 改造 |
|------|------|
| `skills/tools/end/config.json` | `summary` → `action_summary` + `new_info` |
| `skills/tools/end/handler.py` | 构建 memory_job，触发史官后台任务 |
| `ai/prompts.py:207-263` | 全量注入 → 向量查询 + 侧写注入 |
| `ai/client.py` | 初始化 cognitive 模块，注入 tool context |
| `end_summary_storage.py` | 保留作为 fallback |
| `memory.py` | 不变（独立功能） |
| `pyproject.toml` | 新增 `chromadb>=1.0.0` |
| `res/prompts/undefined.xml` | 更新记忆系统说明 |

---

## 8. 配置项

```toml
[cognitive]
enabled = true

[cognitive.embedding]
api_url = ""          # 留空复用 chat 模型
api_key = ""
model = "text-embedding-3-small"

[cognitive.vector_store]
path = "data/chromadb"  # 需重启

[cognitive.query]
auto_top_k = 3
tool_default_top_k = 10

[cognitive.historian]
model_name = ""       # 留空复用 chat 模型
api_url = ""
api_key = ""
```

---

## 9. System Prompt 改造

替换 `undefined.xml` 中的 `<memory_management>` 和 `<end_summary_guidelines>`：

```xml
<cognitive_memory priority="P0">
  **记忆系统**：
  1) 系统已自动注入【用户侧写】【群聊背景】【相关回忆】，优先使用。
  2) 不够用时主动调用 search_events 深度搜索。
  3) 需要了解不在场的用户/群聊时调用 get_profile。

  **end 填写原则**：
  - action_summary：做了什么
  - new_info：获取到的新持久性信息（技术栈、偏好、身份等）
  - 临时信息不写 new_info
</cognitive_memory>
```

---

## 10. 数据迁移

1. 启动时检测：`end_summaries.json` 存在且 ChromaDB `events` 为空 → 批量迁移
2. 后台异步：逐条 embedding → upsert，不阻塞启动
3. 原文件保留备份
4. `memory.py` 不动（独立功能）

---

## 11. 验证

1. **功能**：对话 → end → 检查 `data/chromadb/` 和 `data/profiles/`
2. **查询**：自动注入相关性 + search_events/get_profile 工具
3. **隔离**：群A记忆不出现在群B
4. **降级**：关闭 `cognitive.enabled` 回退旧模式
5. **迁移**：旧 end_summaries.json 正确迁入 ChromaDB

---

## 12. 落地路线

**Step 1 — 接口契约**：改 end 工具为双字段，跑几天验证 LLM 填写质量。

**Step 2 — 史官 + 向量库**：引入 chromadb，实现 historian worker，完成绝对化 + 质量闸门 + 向量入库。

**Step 3 — 检索 + 侧写**：改造 prompts.py 注入逻辑，实现侧写 CRUD 和两个新工具。

---

## 13. 对 Gemini v2 的回应

### 13.1 文件级持久化队列

Gemini 提出用 `data/queues/pending/processing/failed/` 目录结构替代 `asyncio.create_task`，理由是"进程挂了数据就丢了"。

**我的回应**：
- 有道理，但需要权衡。丢失一条 end_summary 的代价是什么？下次对话时 AI 少了一条回忆，仅此而已
- 文件队列增加了显著复杂度：目录扫描循环、文件移动、锁竞争、启动时恢复逻辑
- QQ 机器人不是金融系统，不需要"零丢失"保证

**折中方案**：保持 `asyncio.create_task`，但在 task 开始前先写一份 `memory_job` 到 `data/cognitive_backlog.json`（追加模式），task 成功后删除对应条目。这样崩溃后重启时可以重试，但不需要三个目录的复杂队列。

### 13.2 侧写快照（采纳）

Gemini 提出覆盖前把旧侧写复制到 `history/`。这个建议好——实现成本极低（一行 `shutil.copy`），但提供了回滚能力。

**采纳**：侧写更新前，将旧文件复制到 `data/profiles/history/{type}_{id}_{timestamp}.json`，保留最近 N 份（默认 5）。

### 13.3 Markdown + YAML（维持反对）

理由同前：注入 prompt 时只用 `summary` 字段，LLM 不读 JSON 结构。YAML 输出更易出错。

### 13.4 事件 tags（不采纳）

LLM 生成 tags 增加史官 prompt 复杂度，且 ChromaDB 的向量搜索已经覆盖了语义匹配需求。tags 是冗余的。
