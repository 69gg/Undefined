# Cognitive Memory 实施计划

版本：2026-02-22 v3
基线：`plan/FINAL.md`
原则：复用现有架构（队列/发车/IO/ctx），防竞态，零硬编码，最大化复用知识库基础设施，结构化提取优先

---

## 0. 架构总览

```
前台（主回复链路，零阻塞）                    后台（史官 Worker）
┌─────────────────────────┐                ┌──────────────────────────┐
│ end handler              │                │ HistorianWorker          │
│  ├─ 写 action_summary    │   文件队列     │  ├─ poll pending/        │
│  ├─ 写 new_info          │ ──────────►   │  ├─ LLM 绝对化改写       │
│  └─ 落盘 pending/*.json  │                │  ├─ 正则闸门检查         │
└─────────────────────────┘                │  ├─ ChromaDB upsert      │
                                           │  └─ Profile 合并+快照    │
┌─────────────────────────┐                └──────────────────────────┘
│ PromptBuilder            │                         ▲
│  ├─ 自动检索 events(k=3) │                         │
│  ├─ 注入 user profile    │    ┌────────────────────┘
│  └─ 注入 group profile   │    │ CognitiveService（统一门面）
└─────────────────────────┘    │  ├─ vector_store (ChromaDB)
                               │  ├─ embedder (复用 knowledge.Embedder)
                               │  ├─ reranker (复用 knowledge.Reranker, 可选)
┌─────────────────────────┐    │  ├─ profile_storage
│ cognitive.* 主动工具      │◄──┘  └─ job_queue
│  ├─ search_events        │
│  ├─ get_profile          │
│  └─ search_profiles      │
└─────────────────────────┘
```

---

## 1. 依赖

`chromadb` 已随知识库功能引入 `pyproject.toml`，无需新增依赖。

Embedding / Rerank 请求链路已由知识库实现完整闭环：
- `ai/retrieval.py` → `RetrievalRequester`（统一 embed/rerank API + token 记录）
- `ai/llm.py` → `ModelRequester.embed()` / `.rerank()`（委托 `RetrievalRequester`）
- `knowledge/embedder.py` → `Embedder`（队列+分批+发车间隔）
- `knowledge/reranker.py` → `Reranker`（队列+发车间隔）
- `knowledge/store.py` → `KnowledgeStore`（ChromaDB 封装 + `asyncio.to_thread`）

认知记忆系统**直接复用以上组件**，不重复实现。

---

## 2. 配置层改造

### 2.1 复用现有模型配置

`EmbeddingModelConfig` 和 `RerankModelConfig` 已在 `config/models.py` 中定义，`config/loader.py` 已实现 `[models.embedding]` 和 `[models.rerank]` 段的解析。认知记忆系统直接复用，不新增模型配置类。

现有 `EmbeddingModelConfig` 字段：`api_url`, `api_key`, `model_name`, `queue_interval_seconds`, `dimensions`, `query_instruction`, `document_instruction`。
现有 `RerankModelConfig` 字段：`api_url`, `api_key`, `model_name`, `queue_interval_seconds`, `query_instruction`。

### 2.2 新增 `CognitiveConfig` dataclass

文件：`src/Undefined/config/models.py`

```python
@dataclass
class CognitiveConfig:
    """认知记忆系统配置"""
    enabled: bool = True
    vector_store_path: str = "data/chromadb"
    auto_top_k: int = 3
    tool_default_top_k: int = 12
    profile_top_k: int = 8
    rewrite_max_retry: int = 2
    profile_revision_keep: int = 5
    poll_interval_seconds: float = 1.0
    queue_path: str = "data/queues"
    profiles_path: str = "data/profiles"
```

### 2.3 Config 类扩展

文件：`src/Undefined/config/loader.py`

在 `Config` dataclass 新增字段：

```python
cognitive: CognitiveConfig
```

新增解析方法 `_parse_cognitive_config(data)`，从 `[cognitive]` 段读取，遵循现有 `_get_value` + `_coerce_*` 模式。Embedding/Rerank 模型配置复用现有 `config.embedding_model` 和 `config.rerank_model`，不新增字段。

### 2.4 config.toml.example 新增段

```toml
[cognitive]
enabled = true

[cognitive.vector_store]
path = "data/cognitive/chromadb"

[cognitive.query]
auto_top_k = 3
tool_default_top_k = 12
profile_top_k = 8

[cognitive.historian]
rewrite_max_retry = 2
poll_interval_seconds = 1.0
```

Embedding/Rerank 模型配置复用现有 `[models.embedding]` 和 `[models.rerank]` 段，无需在 `[cognitive]` 下重复。

### 2.5 热更新支持

`cognitive.enabled` 变更**需重启**（底层组件在 `enabled=false` 时不创建，无法热启动）。
`cognitive.query.*`（auto_top_k 等）、`cognitive.historian.poll_interval_seconds` 等查询/调度参数支持热更新（通过 `config_getter()` 实时读取）。
`models.embedding.*` / `models.rerank.*` 变更需重启（Embedder/Reranker 缓存连接）——与知识库行为一致。

---

## 3. 新增模块：`src/Undefined/cognitive/`

### 3.1 Embedding — 复用 `knowledge.Embedder`

**不新建 `cognitive/embedding.py`**。直接复用 `knowledge/embedder.py` 的 `Embedder` 类：

```python
from Undefined.knowledge import Embedder
```

`Embedder` 已实现：
- 队列+发车间隔（`queue_interval_seconds`）
- 分批处理（`batch_size`）
- 通过 `ModelRequester.embed()` → `RetrievalRequester.embed()` 调用 OpenAI 兼容 API
- Token 用量自动记录（`call_type="embedding"`）

认知记忆与知识库**共享同一个 `Embedder` 实例**（在 `main.py` 中创建一次，传给两个系统）。若知识库未启用但认知记忆启用，则由认知记忆独立创建 `Embedder`。

### 3.2 `vector_store.py` — ChromaDB 封装

职责：管理 `events` 和 `profiles` 两个 collection 的 CRUD。参考 `knowledge/store.py` 的 `KnowledgeStore` 模式。

```python
class CognitiveVectorStore:
    def __init__(self, path: str, embedder: Embedder) -> None: ...

    # events
    async def upsert_event(self, event_id: str, document: str, metadata: dict[str, Any]) -> None: ...
    async def query_events(self, query_text: str, top_k: int, where: dict | None) -> list[dict]: ...

    # profiles
    async def upsert_profile(self, profile_id: str, document: str, metadata: dict[str, Any]) -> None: ...
    async def query_profiles(self, query_text: str, top_k: int, where: dict | None) -> list[dict]: ...
```

关键设计：
- 复用 `KnowledgeStore` 的模式：ChromaDB 操作通过 `asyncio.to_thread()` 包装，collection 使用 `embedding_function=None`
- `upsert_event` / `upsert_profile` 先调 `embedder.embed([text])` 获取向量，再 `collection.upsert(embeddings=...)`
- `query_events` / `query_profiles` 先 embed query，再 `collection.query(query_embeddings=...)`
- 与 `KnowledgeStore` 的区别：管理两个 collection（events + profiles），支持 `where` 过滤（group_id/user_id）

### 3.3 `job_queue.py` — 文件持久化队列

职责：`pending/` → `processing/` → 完成删除 / `failed/` 三态流转。

```python
class JobQueue:
    def __init__(self, base_path: str) -> None: ...
    async def enqueue(self, job: dict[str, Any]) -> str: ...          # 写入 pending/{job_id}.json
    async def dequeue(self) -> tuple[str, dict] | None: ...           # 原子移动 pending → processing
    async def complete(self, job_id: str) -> None: ...                # 删除 processing/{job_id}.json
    async def fail(self, job_id: str, error: str) -> None: ...        # 移动到 failed/ 并追加 error
    async def recover_stale(self, timeout_seconds: float) -> int: ... # 启动时恢复 processing → pending
```

防竞态设计：
- `enqueue`：复用 `utils/io.py` 的 `write_json()`（原子写入 + 文件锁）
- `dequeue`：通过 `asyncio.to_thread()` 执行同步 `os.replace()`（跨平台原子操作，与 `io.py` 一致），replace 失败说明被其他协程抢走，返回 None
- `recover_stale`：启动时扫描 `processing/`，将超时任务移回 `pending/`（防崩溃后任务丢失）
- job_id 格式：`{request_id}_{end_seq}_{timestamp_ms}`，天然唯一
- 注：统一使用 `os.replace()` 而非 `os.rename()`，前者在 Windows 上目标已存在时也能原子替换，与 `io.py` 的写入模式一致

### 3.4 `profile_storage.py` — 侧写文件管理

职责：读写 Markdown+YAML Frontmatter 侧写文件，管理快照回滚。

```python
class ProfileStorage:
    def __init__(self, base_path: str, revision_keep: int = 5) -> None: ...
    async def read_profile(self, entity_type: str, entity_id: str) -> str | None: ...
    async def write_profile(self, entity_type: str, entity_id: str, content: str) -> None: ...
    async def list_revisions(self, entity_type: str, entity_id: str) -> list[str]: ...
```

防竞态设计：
- 读写均通过 `utils/io.py` 的模式：`asyncio.to_thread()` + `FileLock`
- 写入前自动备份到 `data/profiles/history/{entity_type}/{entity_id}/{timestamp}.md`
- 备份后原子写入新版本（`write_json` 同款 tmpfile → fsync → replace 模式，但写的是 `.md`）
- 需要新增 `utils/io.py` 的 `write_text()` 函数（与 `write_json` 同模式，只是不做 json.dumps）

YAML Frontmatter 健壮性：
- `write_profile` 写入前调用 `_sanitize_profile(content)` 清洗 LLM 输出：
  1. 剥离开头/结尾的 ` ```markdown ` / ` ``` ` 包裹（LLM 常见格式跑偏）
  2. 用 `yaml.safe_load()` 解析 frontmatter 段，解析失败则 logger.warning 并保留原文降级写入
  3. 校验必要字段存在（`entity_type`、`entity_id`），缺失则从参数补全
- `read_profile` 返回原始 Markdown 文本，不做解析（消费方只需正文）

---

## 4. 后台史官 `historian.py`

### 4.1 HistorianWorker 类

文件：`src/Undefined/cognitive/historian.py`

```python
class HistorianWorker:
    def __init__(
        self,
        job_queue: JobQueue,
        vector_store: VectorStore,
        profile_storage: ProfileStorage,
        ai_client: AIClient,           # 复用主 AIClient 调模型
        config_getter: Callable[[], CognitiveConfig],
    ) -> None: ...

    async def start(self) -> None: ...  # 启动轮询循环
    async def stop(self) -> None: ...   # 优雅停止
```

### 4.2 处理流水线（单个 job）

```
1. dequeue() 取任务
2. 调 LLM 绝对化改写 → canonical_text
3. 正则闸门检查（代词/相对时间/相对地点）
4. 不通过 → 回炉重写（最多 rewrite_max_retry 次）
5. 仍不通过 → 降级写入（metadata 标记 is_absolute=false）+ logger.warning
6. vector_store.upsert_event(event_id, canonical_text, metadata)
7. 若 has_new_info → 通过 tool_call 结构化提取 profile 字段 → _sanitize_profile 校验 → profile_storage.write_profile() → vector_store.upsert_profile()
8. job_queue.complete(job_id)
9. 异常 → job_queue.fail(job_id, error)
```

### 4.3 绝对化 LLM 调用

- 复用 `ai_client.request_model()`，使用 `agent_model` 配置（与 Agent 共享模型配置）
- call_type = `"historian_rewrite"`（便于 token 统计区分）
- 提示词文件：`res/prompts/historian_rewrite.md`（新增）

### 4.3.1 Profile 合并——tool_call 结构化提取

Profile 合并**不使用自由文本输出**，而是通过 tool_call 强制结构化返回，避免 LLM 输出格式跑偏（如多余的 ` ```markdown ` 包裹、YAML 语法错误等）。

调用方式：`ai_client.request_model()` 时传入 `tools` 参数，定义一个 `update_profile` 工具：

```python
_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_profile",
        "description": "更新用户/群侧写",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "用户/群名称"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "兴趣/技能标签"},
                "summary": {"type": "string", "description": "侧写正文（Markdown）"},
            },
            "required": ["name", "tags", "summary"],
        },
    },
}
```

LLM 返回 tool_call 后，HistorianWorker 从 `arguments` 中提取结构化字段，自行拼装 YAML frontmatter + Markdown 正文，**完全绕过 LLM 的格式不确定性**。

调用时**必须指定 `tool_choice` 强制约束**，确保 LLM 不会用纯文本回复：

```python
response = await self.ai_client.request_model(
    messages=messages,
    tools=[_PROFILE_TOOL],
    tool_choice={"type": "function", "function": {"name": "update_profile"}},
    call_type="historian_profile_merge",
)
# response 必定包含 tool_call，直接从 arguments 提取结构化字段
args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
```

call_type = `"historian_profile_merge"`（便于 token 统计区分）
提示词文件：`res/prompts/historian_profile_merge.md`（新增）

### 4.4 正则闸门

```python
_PRONOUN_RE = re.compile(r"(?<![a-zA-Z])(我|你|他|她|它|他们|她们|它们|这位|那位)(?![a-zA-Z])")
_REL_TIME_RE = re.compile(r"(今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近)")
_REL_PLACE_RE = re.compile(r"(这里|那边|本地|当地|这儿|那儿)")
```

检查 `canonical_text`，命中任一则判定违规。

**降级写入策略**：重试 `rewrite_max_retry` 次仍不通过时，不丢弃数据，而是：
- 照常写入 ChromaDB `events` collection
- metadata 中标记 `is_absolute: false`（区别于正常通过闸门的 `is_absolute: true`）
- logger.warning 记录降级事件，便于后续排查

**误伤说明**：正则可能误伤合法专有名词（如歌名《今天》、书名《你不知道的Python》）。降级标记确保这类事件仍能入库被检索到，不会永久丢失。后续可考虑引入白名单或更智能的 NER 判断，但首版以简单可靠为优先。

### 4.5 与 QueueManager 的关系

HistorianWorker 是**独立的后台循环**，不走 QueueManager 的"车站-列车"调度。原因：
- 史官任务无优先级区分，无需多队列轮转
- 史官任务不需要按模型隔离队列（统一用 agent_model）
- 但**复用 QueueManager 的设计模式**：独立 `asyncio.Task` + `asyncio.Event` 停止信号 + 在途任务追踪

---

## 5. 前台改造：end 工具

### 5.1 `end/config.json` 参数升级

文件：`src/Undefined/skills/tools/end/config.json`

新增 `action_summary` 和 `new_info` 参数，保留 `summary` 做兼容：

```json
{
  "type": "function",
  "function": {
    "name": "end",
    "description": "结束当前对话。必须提供 action_summary 描述本轮做了什么。如果本轮获得了关于用户/群的新信息（偏好、身份、习惯等），填写 new_info。",
    "parameters": {
      "type": "object",
      "properties": {
        "action_summary": {
          "type": "string",
          "description": "本轮做了什么（必填）"
        },
        "new_info": {
          "type": "string",
          "description": "本轮获得的新信息（可空）"
        },
        "summary": {
          "type": "string",
          "description": "[过渡兼容] 旧版摘要字段，优先使用 action_summary"
        },
        "force": {
          "type": "boolean",
          "description": "强制结束，跳过未发送消息检查"
        }
      },
      "required": []
    }
  }
}
```

### 5.2 `end/handler.py` 改造

核心变更：

```python
async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    # 1. 兼容映射：旧 summary → action_summary
    action_summary = args.get("action_summary") or args.get("summary", "")
    new_info = args.get("new_info", "")
    force = args.get("force", False)

    # 2. 原有逻辑不变：检查是否发送过消息、写 end_summary_storage
    # ...（保持现有 end_summary_storage 写入，确保旧模式可回退）

    # 3. 新增：若 cognitive 启用，入队 memory_job
    cognitive_service = context.get("cognitive_service")
    if cognitive_service and action_summary:
        await cognitive_service.enqueue_job(
            action_summary=action_summary,
            new_info=new_info,
            context=context,
        )

    context["conversation_ended"] = True
    return "对话已结束"
```

关键设计：
- **双写过渡**：同时写旧 `end_summaries.json` 和新 cognitive 队列，`cognitive.enabled=false` 时只走旧路径
- `cognitive_service` 通过 `context` 注入（与 `memory_storage`、`end_summary_storage` 同一模式）
- `enqueue_job` 内部只做文件落盘（`job_queue.enqueue()`），p95 < 5ms，不阻塞主链路

---

## 6. 前台改造：PromptBuilder 注入认知记忆

### 6.1 PromptBuilder 构造函数扩展

文件：`src/Undefined/ai/prompts.py`

新增可选参数：

```python
class PromptBuilder:
    def __init__(
        self,
        # ...现有参数不变...
        cognitive_service: CognitiveService | None = None,  # 新增
    ) -> None:
```

### 6.2 `build_messages()` 新增注入点

**重要语义澄清**：双写始终进行（end handler 同时写旧 `end_summary_storage` 和新 cognitive 队列），此处的"替代"仅指 **prompt 注入时二选一**——cognitive 启用时注入向量检索结果，否则注入旧 end_summaries 列表。旧存储的写入不受影响，确保随时可回退。

在现有"短期回忆 (End 摘要)"注入之后、"历史消息上下文"注入之前，新增认知记忆注入：

```python
# === 认知记忆注入（prompt 注入时二选一，写入端始终双写）===
if self._cognitive_service and self._cognitive_service.enabled:
    cognitive_context = await self._cognitive_service.build_context(
        query=question,
        # 从 RequestContext 或 extra_context 获取 scope
    )
    if cognitive_context:
        messages.append({
            "role": "system",
            "content": cognitive_context,
        })
else:
    # 旧模式：注入 end_summaries（现有逻辑不变）
    ...
```

### 6.3 `CognitiveService.build_context()` 返回格式

```
【认知记忆】

[用户侧写] {user_id}: {user_name}
{profile_content}

[群聊侧写] {group_id}: {group_name}
{profile_content}

[相关事件回忆]
- [2026-02-20 14:30 UTC+8] 用户Null在Python群讨论了异步IO的最佳实践
- [2026-02-19 10:00 UTC+8] 用户Null请求帮助设计QQ机器人的记忆架构
- ...
```

### 6.4 自动检索的 scope 过滤

从 `RequestContext` 获取 `group_id` / `user_id`，传入 ChromaDB `where` 过滤：

- 群聊：`{"group_id": current_group_id}` → 只召回本群事件
- 私聊：`{"user_id": current_user_id}` → 只召回该用户事件
- 跨群误召回 = 0（硬过滤，不依赖向量相似度）

---

## 7. 主动工具：`skills/toolsets/cognitive/`

遵循现有 toolset 模式（`config.json` + `handler.py`），注册名前缀 `cognitive.`。

### 7.1 `cognitive/search_events/`

`config.json`:
```json
{
  "type": "function",
  "function": {
    "name": "search_events",
    "description": "搜索历史事件记忆。用于回忆之前发生过的事情。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "搜索关键词或语义描述" },
        "target_user_id": { "type": "string", "description": "限定用户ID（可选）" },
        "target_group_id": { "type": "string", "description": "限定群ID（可选）" },
        "top_k": { "type": "integer", "description": "返回条数，默认12" },
        "time_from": { "type": "string", "description": "起始时间 ISO格式（可选）" },
        "time_to": { "type": "string", "description": "截止时间 ISO格式（可选）" }
      },
      "required": ["query"]
    }
  }
}
```

`handler.py`:
```python
async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    cognitive_service = context.get("cognitive_service")
    if not cognitive_service or not cognitive_service.enabled:
        return "认知记忆系统未启用"
    results = await cognitive_service.search_events(
        query=args["query"],
        target_user_id=args.get("target_user_id"),
        target_group_id=args.get("target_group_id"),
        top_k=args.get("top_k", 12),
        time_from=args.get("time_from"),
        time_to=args.get("time_to"),
    )
    if not results:
        return "未找到相关事件记忆"
    lines = [f"- [{r['timestamp']}] {r['document']}" for r in results]
    return f"找到 {len(results)} 条相关事件：\n" + "\n".join(lines)
```

### 7.2 `cognitive/get_profile/`

`config.json`:
```json
{
  "type": "function",
  "function": {
    "name": "get_profile",
    "description": "获取用户或群聊的侧写信息。",
    "parameters": {
      "type": "object",
      "properties": {
        "entity_type": { "type": "string", "enum": ["user", "group"], "description": "实体类型" },
        "entity_id": { "type": "string", "description": "用户ID或群ID" }
      },
      "required": ["entity_type", "entity_id"]
    }
  }
}
```

`handler.py`: 调用 `cognitive_service.get_profile()`，返回 Markdown 正文或"暂无侧写"。

### 7.3 `cognitive/search_profiles/`

`config.json`:
```json
{
  "type": "function",
  "function": {
    "name": "search_profiles",
    "description": "语义搜索用户/群聊侧写。用于查找具有特定特征的用户或群。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": { "type": "string", "description": "搜索关键词" },
        "entity_type": { "type": "string", "enum": ["user", "group"], "description": "限定类型（可选）" },
        "top_k": { "type": "integer", "description": "返回条数，默认8" }
      },
      "required": ["query"]
    }
  }
}
```

`handler.py`: 调用 `cognitive_service.search_profiles()`，格式化返回。

---

## 8. 统一门面：`CognitiveService`

文件：`src/Undefined/cognitive/service.py`

所有外部模块（end handler、PromptBuilder、toolset handler）只依赖此门面，不直接接触底层组件。

```python
class CognitiveService:
    """认知记忆系统统一入口"""

    def __init__(
        self,
        config_getter: Callable[[], CognitiveConfig],
        vector_store: VectorStore,
        job_queue: JobQueue,
        profile_storage: ProfileStorage,
    ) -> None: ...

    @property
    def enabled(self) -> bool:
        """运行时检查 cognitive.enabled，支持热更新开关"""
        return self._config_getter().enabled

    # --- 前台入队（end handler 调用）---
    async def enqueue_job(
        self,
        action_summary: str,
        new_info: str,
        context: dict[str, Any],
    ) -> str | None:
        """构造 memory_job 并落盘到 pending/，返回 job_id"""
        ...

    # --- 自动检索（PromptBuilder 调用）---
    async def build_context(
        self,
        query: str,
        group_id: str | None = None,
        user_id: str | None = None,
        sender_id: str | None = None,
    ) -> str:
        """构建注入 prompt 的认知记忆上下文"""
        ...

    # --- 主动工具 ---
    async def search_events(self, query: str, **kwargs: Any) -> list[dict]: ...
    async def get_profile(self, entity_type: str, entity_id: str) -> str | None: ...
    async def search_profiles(self, query: str, **kwargs: Any) -> list[dict]: ...
```

### 8.1 `enqueue_job` 内部逻辑

```python
async def enqueue_job(self, action_summary, new_info, context):
    if not self.enabled or not action_summary:
        return None
    ctx = RequestContext.current()
    job = {
        "request_id": ctx.request_id if ctx else str(uuid4()),
        "end_seq": context.get("_end_seq", 0),
        "action_summary": action_summary,
        "new_info": new_info,
        "has_new_info": bool(new_info and new_info.strip()),
        "timestamp_utc": datetime.utcnow().isoformat(),
        "timestamp_local": datetime.now().isoformat(),
        "timezone": "Asia/Shanghai",  # 从 config 或系统获取
        "request_type": ctx.request_type if ctx else "private",
        "user_id": str(ctx.user_id) if ctx and ctx.user_id else "",
        "group_id": str(ctx.group_id) if ctx and ctx.group_id else "",
        "sender_id": str(ctx.sender_id) if ctx and ctx.sender_id else "",
        "schema_version": "final_v1",
    }
    return await self._job_queue.enqueue(job)
```

### 8.2 `build_context` 内部逻辑

```python
async def build_context(self, query, group_id, user_id, sender_id):
    parts: list[str] = []
    config = self._config_getter()

    # 1. 用户侧写
    target_id = sender_id or user_id
    if target_id:
        profile = await self._profile_storage.read_profile("user", target_id)
        if profile:
            parts.append(f"[用户侧写] {target_id}\n{profile}")

    # 2. 群聊侧写
    if group_id:
        profile = await self._profile_storage.read_profile("group", group_id)
        if profile:
            parts.append(f"[群聊侧写] {group_id}\n{profile}")

    # 3. 相关事件（自动检索，小 top_k）
    where = {"group_id": group_id} if group_id else {"user_id": target_id} if target_id else None
    events = await self._vector_store.query_events(query, top_k=config.auto_top_k, where=where)
    if events:
        lines = [f"- [{e['metadata']['timestamp_local']}] {e['document']}" for e in events]
        parts.append("[相关事件回忆]\n" + "\n".join(lines))

    if not parts:
        return ""
    return "【认知记忆】\n\n" + "\n\n".join(parts)
```

---

## 9. `main.py` 集成

### 9.1 初始化顺序

在现有组件初始化之后、`MessageHandler` 创建之前：

```python
# === Cognitive Memory ===
cognitive_service: CognitiveService | None = None
historian_worker: HistorianWorker | None = None

if config.cognitive.enabled:
    from Undefined.cognitive.vector_store import CognitiveVectorStore
    from Undefined.cognitive.job_queue import JobQueue
    from Undefined.cognitive.profile_storage import ProfileStorage
    from Undefined.cognitive.service import CognitiveService
    from Undefined.cognitive.historian import HistorianWorker
    from Undefined.knowledge import Embedder, Reranker

    # 复用知识库的 Embedder/Reranker 实例（若已创建），否则独立创建
    if not hasattr(ai, '_embedder') or ai._embedder is None:
        _cognitive_embedder = Embedder(ai._requester, config.embedding_model)
        _cognitive_embedder.start()
    else:
        _cognitive_embedder = ai._embedder  # 共享知识库实例

    _cognitive_reranker: Reranker | None = None
    if config.rerank_model.api_url and config.rerank_model.model_name:
        _cognitive_reranker = ...  # 同理复用或创建

    vector_store = CognitiveVectorStore(config.cognitive.vector_store_path, _cognitive_embedder)
    job_queue = JobQueue(config.cognitive.queue_path)
    profile_storage = ProfileStorage(
        config.cognitive.profiles_path,
        revision_keep=config.cognitive.profile_revision_keep,
    )
    cognitive_service = CognitiveService(
        config_getter=lambda: config.cognitive,
        vector_store=vector_store,
        job_queue=job_queue,
        profile_storage=profile_storage,
        reranker=_cognitive_reranker,
    )
    historian_worker = HistorianWorker(
        job_queue=job_queue,
        vector_store=vector_store,
        profile_storage=profile_storage,
        ai_client=ai,
        config_getter=lambda: config.cognitive,
    )
```

### 9.2 运行时目录

在 `ensure_runtime_dirs()` 中新增：

```python
if config.cognitive.enabled:
    for sub in ["pending", "processing", "failed"]:
        Path(config.cognitive.queue_path, sub).mkdir(parents=True, exist_ok=True)
    for sub in ["users", "groups", "history"]:
        Path(config.cognitive.profiles_path, sub).mkdir(parents=True, exist_ok=True)
    Path(config.cognitive.vector_store_path).mkdir(parents=True, exist_ok=True)
```

### 9.3 启动与停止

```python
# 启动（在 onebot.run_with_reconnect() 之前）
if historian_worker:
    await job_queue.recover_stale(timeout_seconds=300)
    await historian_worker.start()

# 停止（在 finally 块中）
if historian_worker:
    await historian_worker.stop()
```

### 9.4 context 注入

`cognitive_service` 需要到达两个消费方：PromptBuilder（自动检索）和 tool handler（主动工具 + end 工具）。

**PromptBuilder 路径**（直接持有）：

```python
# ai/client.py 的 __init__ 中
self._prompt_builder = PromptBuilder(
    ...,
    cognitive_service=cognitive_service,  # 新增
)
```

**tool handler 路径**（通过 ToolManager context 注入）：

实际链路：`main.py` → `AIClient` → `ToolManager._build_context()` → handler 的 `context` 字典。

```python
# ai/client.py 的 __init__ 新增
self._cognitive_service = cognitive_service

# ToolManager 构建 context 时（ai/tooling.py）
# 在现有 context 字典中追加：
tool_context["cognitive_service"] = self._ai_client._cognitive_service
```

注意：需要确认 `ToolManager` 构建 context 的具体位置（`ai/tooling.py` 中搜索 `context` 字典构建），在现有 `end_summary_storage`、`memory_storage` 等注入点旁边追加即可。

`AIClient.__init__` 新增可选参数 `cognitive_service: CognitiveService | None = None`。
`PromptBuilder.__init__` 新增可选参数 `cognitive_service: CognitiveService | None = None`。

---

## 10. 提示词改造

### 10.1 系统提示词 `res/prompts/undefined.xml` 和 `undefined_nagaagent.xml`

在 `<memory_management>` 或等效段落中，新增 cognitive 相关指引：

```xml
<end_tool_usage>
  调用 end 时必须提供：
  - action_summary：本轮做了什么（必填）
  - new_info：本轮获得的关于用户/群的新信息（偏好、身份、习惯等，可空）
  new_info 要求具体、绝对化（写明谁、什么时候、在哪里），避免代词和相对时间。
</end_tool_usage>
```

### 10.2 新增提示词文件

`res/prompts/historian_rewrite.md`：

```markdown
你是一个记忆整理员。将以下对话摘要改写为绝对化的事件记录。

要求：
1. 消灭所有代词（我、你、他、她），替换为具体的人名/ID
2. 消灭所有相对时间（今天、昨天、刚才），替换为绝对时间
3. 消灭所有相对地点（这里、那边），替换为具体地点
4. 保持简洁，一两句话概括

上下文信息：
- 时间：{timestamp_local}（{timezone}）
- 用户：{user_id}
- 群聊：{group_id}（如有）
- 发送者：{sender_id}

原始摘要：
action_summary: {action_summary}
new_info: {new_info}

请输出改写后的 canonical_text（纯文本，不要 JSON）：
```

`res/prompts/historian_profile_merge.md`：

```markdown
你是一个用户画像维护员。根据新事件更新侧写。

当前侧写：
{current_profile}

新事件：
{canonical_text}

新信息：
{new_info}

要求：
1. 保留现有稳定特征，整合新信息
2. 矛盾时以新信息为准
3. tags 字段反映用户的主要兴趣/技能标签
4. 保持简洁，只记录长期稳定的特征

请调用 update_profile 工具输出更新后的侧写。
```

HistorianWorker 收到 tool_call 后自行拼装最终文件：

```python
# 从 tool_call arguments 提取
args = json.loads(tool_call.function.arguments)
frontmatter = {
    "entity_type": entity_type,
    "entity_id": entity_id,
    "name": args["name"],
    "tags": args["tags"],
    "updated_at": datetime.now().isoformat(),
    "source_event_id": event_id,
}
content = f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n{args['summary']}"
await profile_storage.write_profile(entity_type, entity_id, content)
```

这样 YAML frontmatter 的格式完全由代码控制，LLM 只负责提供内容字段，消除格式脆弱性。

---

## 11. `utils/io.py` 扩展

新增 `write_text()` 和 `read_text()` 函数，与现有 `write_json()` / `read_json()` 同模式：

```python
async def write_text(file_path: str | Path, content: str, use_lock: bool = True) -> None:
    """原子写入文本文件（tmpfile → fsync → replace）"""
    target = Path(file_path)
    await asyncio.to_thread(_write_text_sync, target, content, use_lock)

async def read_text(file_path: str | Path, use_lock: bool = False) -> str | None:
    """异步读取文本文件"""
    target = Path(file_path)
    return await asyncio.to_thread(_read_text_sync, target, use_lock)
```

内部同步函数复用现有 `write_json` 的 tmpfile + fsync + replace 模式，只是序列化步骤从 `json.dumps` 改为直接 `str.encode`。

---

## 12. 完整文件清单

### 12.1 新增文件

| 文件 | 职责 |
|------|------|
| `src/Undefined/cognitive/__init__.py` | 包初始化 |
| `src/Undefined/cognitive/vector_store.py` | ChromaDB 封装（events + profiles） |
| `src/Undefined/cognitive/job_queue.py` | 文件持久化队列 |
| `src/Undefined/cognitive/profile_storage.py` | 侧写文件管理 |
| `src/Undefined/cognitive/historian.py` | 后台史官 Worker |
| `src/Undefined/cognitive/service.py` | 统一门面 CognitiveService |
| `src/Undefined/skills/toolsets/cognitive/search_events/config.json` | 搜索事件工具定义 |
| `src/Undefined/skills/toolsets/cognitive/search_events/handler.py` | 搜索事件处理器 |
| `src/Undefined/skills/toolsets/cognitive/get_profile/config.json` | 获取侧写工具定义 |
| `src/Undefined/skills/toolsets/cognitive/get_profile/handler.py` | 获取侧写处理器 |
| `src/Undefined/skills/toolsets/cognitive/search_profiles/config.json` | 搜索侧写工具定义 |
| `src/Undefined/skills/toolsets/cognitive/search_profiles/handler.py` | 搜索侧写处理器 |
| `res/prompts/historian_rewrite.md` | 绝对化改写提示词 |
| `res/prompts/historian_profile_merge.md` | 侧写合并提示词 |

注意：**不新建** `cognitive/embedding.py`（复用 `knowledge/embedder.py`）和 `cognitive/reranker.py`（复用 `knowledge/reranker.py`）。

### 12.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/Undefined/config/models.py` | 新增 `CognitiveConfig`（`EmbeddingModelConfig` 已存在） |
| `src/Undefined/config/loader.py` | Config 新增 `cognitive` 字段 + `_parse_cognitive_config` |
| `src/Undefined/skills/tools/end/config.json` | 新增 `action_summary`、`new_info` 参数 |
| `src/Undefined/skills/tools/end/handler.py` | 兼容映射 + cognitive 入队 |
| `src/Undefined/ai/prompts.py` | PromptBuilder 注入认知记忆 |
| `src/Undefined/ai/client.py` | 新增 `cognitive_service` 参数 + context 注入 |
| `src/Undefined/main.py` | 初始化 cognitive 组件（共享 Embedder）+ 启停 |
| `src/Undefined/utils/io.py` | 新增 `write_text()` / `read_text()` |
| `res/prompts/undefined.xml` | end 工具使用指引 |
| `res/prompts/undefined_nagaagent.xml` | 同上 |
| `config.toml.example` | 新增 `[cognitive]` 配置段 |

### 12.3 运行时目录（自动创建，不提交）

```
data/cognitive/chromadb/           # ChromaDB 持久化
data/cognitive/profiles/users/     # 用户侧写
data/cognitive/profiles/groups/    # 群聊侧写
data/cognitive/profiles/history/   # 侧写快照
data/cognitive/queues/pending/     # 待处理任务
data/cognitive/queues/processing/  # 处理中任务
data/cognitive/queues/failed/      # 失败任务
```

---

## 13. 防竞态与并发安全总结

本项目涉及多个并发写入点，以下逐一说明防护策略：

### 13.1 文件队列（JobQueue）

| 操作 | 竞态风险 | 防护 |
|------|---------|------|
| `enqueue` | 多个 end 并发写入 pending/ | 每个 job 文件名含 uuid，天然无冲突；`io.write_json` 原子写入 |
| `dequeue` | 多协程同时抢同一个 job | `os.replace()` 跨平台原子性，replace 失败 = 被抢走，返回 None |
| `complete` / `fail` | 单 job 只有一个 worker 持有 | 无竞态（processing 中的 job 已被独占） |
| `recover_stale` | 仅启动时执行一次 | 无并发（main.py 串行调用） |

### 13.2 侧写文件（ProfileStorage）

| 操作 | 竞态风险 | 防护 |
|------|---------|------|
| `write_profile` | 史官并发更新同一用户侧写 | `asyncio.Lock` 按 entity_id 粒度 + `FileLock` 文件级锁 |
| `read_profile` | 读写并发 | 原子写入保证读到完整文件（不会读到半写状态） |
| 快照备份 | 备份与写入的原子性 | 先备份再 replace，备份失败不影响主文件 |

实现：`ProfileStorage` 内部维护 `dict[str, asyncio.Lock]` 按 `{entity_type}:{entity_id}` 粒度锁，防止同一实体的并发写入。

### 13.3 ChromaDB（VectorStore）

| 操作 | 竞态风险 | 防护 |
|------|---------|------|
| `upsert_event` | 并发 upsert 不同 event_id | ChromaDB 内部线程安全，无需额外锁 |
| `upsert_profile` | 并发 upsert 同一 profile_id | ChromaDB upsert 幂等，最后写入者胜 |
| `query_*` | 读写并发 | ChromaDB 内部 MVCC，读不阻塞写 |

### 13.4 Embedding API 调用

| 操作 | 竞态风险 | 防护 |
|------|---------|------|
| 并发 embed 请求 | API 限流 | 复用 `Embedder` 的队列+发车间隔机制（`queue_interval_seconds`），天然串行化 |

### 13.5 RequestContext 传播

end handler → `enqueue_job` 时，从 `RequestContext.current()` 提取所有上下文字段（request_id、group_id、user_id、sender_id），**在入队时快照到 job JSON 中**，不依赖后续 ctx 存活。

这确保了：
- 前台 ctx 生命周期结束后，后台史官仍能获取完整上下文
- 不存在 ctx 跨协程泄漏风险

---

## 14. 复用清单（避免重复造轮子）

| 现有组件 | 复用方式 |
|---------|---------|
| **`knowledge/embedder.py` Embedder** | **直接复用**：认知记忆与知识库共享同一 Embedder 实例，队列+分批+发车间隔 |
| **`knowledge/reranker.py` Reranker** | **直接复用**：可选重排，共享实例 |
| **`knowledge/store.py` KnowledgeStore 模式** | CognitiveVectorStore 参考其 ChromaDB + asyncio.to_thread 封装模式 |
| **`ai/retrieval.py` RetrievalRequester** | Embedder/Reranker 底层已通过它调用 API + 记录 token |
| **`ai/llm.py` ModelRequester.embed()/.rerank()** | 已实现，无需新增方法 |
| `utils/io.py` write_json / read_json | JobQueue 的 enqueue/dequeue 直接调用 |
| `utils/io.py` FileLock + 原子写入模式 | ProfileStorage 的 write_profile 复刻同一模式（新增 write_text） |
| `RequestContext` contextvars | enqueue_job 时快照 ctx 字段到 job JSON |
| `AIClient.request_model()` | HistorianWorker 调 LLM 做绝对化改写和 profile 合并 |
| `utils/resources.py` read_text_resource | 加载 historian 提示词文件 |
| `QueueManager` 设计模式 | HistorianWorker 的 asyncio.Task + Event 停止信号 |
| `EndSummaryStorage` 双锁模式 | ProfileStorage 的 asyncio.Lock + FileLock 组合 |
| `config/loader.py` _get_value + _coerce_* | 解析 [cognitive] 配置段 |
| toolset `config.json` + `handler.py` 模式 | cognitive 三个主动工具完全遵循 |
| `context` 字典注入模式 | cognitive_service 通过 tool_context 注入 handler |

---

## 15. 分阶段实施

### Phase 1：基础设施 + end 参数升级

目标：跑通配置加载、end 双字段、文件队列，旧模式不受影响。

步骤：

1. `config/models.py`：新增 `CognitiveConfig`（`EmbeddingModelConfig` 已存在）
2. `config/loader.py`：新增 `_parse_cognitive_config`，Config 新增 `cognitive` 字段
3. `config.toml.example`：新增 `[cognitive]` 段
4. `utils/io.py`：新增 `write_text()` / `read_text()`
5. `cognitive/__init__.py`：空包
6. `cognitive/job_queue.py`：实现 `JobQueue`（enqueue / dequeue / complete / fail / recover_stale）
7. `skills/tools/end/config.json`：新增 `action_summary`、`new_info` 参数
8. `skills/tools/end/handler.py`：兼容映射 + cognitive 入队（此时 cognitive_service 为 None，走旧路径）
9. `res/prompts/undefined.xml` + `undefined_nagaagent.xml`：更新 end 工具使用指引

验证：
- `cognitive.enabled = false` 时行为与改造前完全一致
- end 工具接受新旧两种参数格式
- `data/queues/pending/` 下能正确生成 job 文件（手动测试 `enabled = true`）

### Phase 2：向量存储 + 史官 Worker

目标：跑通"对话 → 落队列 → 史官改写 → 写入 ChromaDB"。

步骤：

1. `cognitive/vector_store.py`：实现 `CognitiveVectorStore`（events + profiles collection，复用 `KnowledgeStore` 模式）
2. `res/prompts/historian_rewrite.md`：绝对化改写提示词
3. `cognitive/historian.py`：实现 `HistorianWorker`（轮询 + LLM 改写 + 正则闸门 + upsert events）
4. `main.py`：条件初始化 cognitive 组件（共享 `Embedder` 实例）+ 启停 historian

验证：
- 对话结束后，`data/queues/pending/` 中的 job 被消费
- ChromaDB `events` collection 中能查到绝对化后的事件
- 正则闸门能拦截含代词/相对时间的文本
- 进程重启后 `processing/` 中的任务能恢复

### Phase 3：侧写 + 自动检索 + 主动工具

目标：完整闭环——侧写生成、prompt 注入、主动工具可用。

步骤：

1. `cognitive/profile_storage.py`：实现 `ProfileStorage`（读写 + 快照）
2. `res/prompts/historian_profile_merge.md`：侧写合并提示词
3. `cognitive/historian.py`：补充 profile 合并逻辑（has_new_info 分支）
4. `cognitive/service.py`：实现 `CognitiveService`（enqueue_job / build_context / search_* / get_profile）
5. `ai/prompts.py`：PromptBuilder 注入认知记忆
6. `ai/client.py`：新增 cognitive_service 参数 + context 注入
7. `main.py`：将 cognitive_service 传入 AIClient 和 PromptBuilder
8. `skills/toolsets/cognitive/search_events/`：config.json + handler.py
9. `skills/toolsets/cognitive/get_profile/`：config.json + handler.py
10. `skills/toolsets/cognitive/search_profiles/`：config.json + handler.py

验证：
- 对话中 AI 能看到用户侧写和相关事件回忆
- `cognitive.search_events` 工具能返回语义相关的事件
- 群聊不会召回其他群的事件（跨群误召回 = 0）
- `cognitive.enabled = false` 时完整回退旧模式

### Phase 4：收尾

目标：监控、旧数据迁移、灰度验证。

步骤：

1. 添加日志埋点：史官任务成功率、处理时延、闸门通过率
2. 编写迁移脚本：旧 `end_summaries.json` → ChromaDB `events`（一次性）
3. 灰度：先在测试群开启 `cognitive.enabled = true`，观察 1-2 天
4. 全量：确认无误后全量开启

---

## 16. 验收标准

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 前台 end 延迟增量 | p95 < 30ms | 对比 enqueue_job 前后的 `time.perf_counter()` |
| 史官任务成功率 | > 99% | `completed / (completed + failed)` 日志统计 |
| 绝对化闸门最终通过率 | > 99% | 含降级写入的通过率 |
| 跨群误召回 | = 0 | ChromaDB where 过滤 + 人工抽检 |
| 关闭 cognitive 回退 | 完整可用 | `cognitive.enabled = false` 后所有旧功能正常 |
| end 旧参数兼容 | 100% | 仅传 `summary` 时行为不变 |

---

## 17. 回退策略

三级回退，逐级递进：

1. **重启回退**：`config.toml` 中设置 `cognitive.enabled = false` 后重启。PromptBuilder 回退到旧 end_summaries 注入，end handler 只走旧路径，cognitive 工具返回"未启用"。pending/ 中未消费的 job 保留不丢失，下次重新启用时继续处理。

2. **侧写回滚**：若某用户侧写被错误更新，从 `data/cognitive/profiles/history/{type}/{id}/` 中选择正确版本覆盖回去。

3. **完整移除**：删除 `data/cognitive/` 目录，设置 `cognitive.enabled = false`，系统完全回到改造前状态。旧 `end_summaries.json` 在整个过渡期保持双写，不会丢失。

---

## 18. 本版刻意不做

与 FINAL.md §9 保持一致：

1. 不做 confidence/deprecated 体系
2. 不引入 Redis/Kafka/PostgreSQL
3. 不做多级 profile chunk 策略
4. 不做 HistorianWorker 多实例并发（单 worker 足够，后续按需扩展）
5. 不做 embedding 缓存（ChromaDB 自带去重，首版不优化）

---

## 19. 数据目录规范与自动管理

### 19.1 目录结构

所有运行时数据统一落盘在 `data/` 下，遵循现有 `data/history/`、`data/faq/`、`data/cache/` 的分层惯例：

```
data/
├── cognitive/                      # 认知记忆系统根目录
│   ├── chromadb/                   # ChromaDB 向量库持久化
│   ├── profiles/                   # 侧写文件
│   │   ├── users/{user_id}.md      # 用户侧写
│   │   ├── groups/{group_id}.md    # 群聊侧写
│   │   └── history/                # 侧写快照（自动清理）
│   │       ├── users/{user_id}/    # 按实体分目录
│   │       └── groups/{group_id}/
│   └── queues/                     # 文件持久化队列
│       ├── pending/                # 待处理
│       ├── processing/             # 处理中
│       └── failed/                 # 失败（自动清理）
├── history/                        # （现有）消息历史
├── faq/                            # （现有）FAQ
├── cache/                          # （现有）缓存
│   ├── render/
│   ├── images/
│   ├── downloads/
│   ├── text_files/
│   └── url_files/
├── memory.json                     # （现有）长期记忆
├── end_summaries.json              # （现有，过渡期保留双写）
├── scheduled_tasks.json            # （现有）定时任务
└── token_usage.jsonl               # （现有）Token 统计
```

设计理由：
- `data/cognitive/` 作为子目录而非 `data/chromadb/` + `data/profiles/` + `data/queues/` 散落，便于整体备份/删除/回退
- 侧写快照按 `history/{entity_type}/{entity_id}/` 分目录，避免单目录文件过多
- 与 FINAL.md §2.3 的路径约定对齐，但统一收纳到 `data/cognitive/` 前缀下

### 19.2 目录自动创建（复用现有模式）

复用 `utils/paths.py` 的 `ensure_dir()` 和 `main.py` 的 `ensure_runtime_dirs()` 模式。

**`utils/paths.py` 新增常量：**

```python
# Cognitive Memory
COGNITIVE_DIR = DATA_DIR / "cognitive"
COGNITIVE_CHROMADB_DIR = COGNITIVE_DIR / "chromadb"
COGNITIVE_PROFILES_DIR = COGNITIVE_DIR / "profiles"
COGNITIVE_PROFILES_USERS_DIR = COGNITIVE_PROFILES_DIR / "users"
COGNITIVE_PROFILES_GROUPS_DIR = COGNITIVE_PROFILES_DIR / "groups"
COGNITIVE_PROFILES_HISTORY_DIR = COGNITIVE_PROFILES_DIR / "history"
COGNITIVE_QUEUES_DIR = COGNITIVE_DIR / "queues"
COGNITIVE_QUEUES_PENDING_DIR = COGNITIVE_QUEUES_DIR / "pending"
COGNITIVE_QUEUES_PROCESSING_DIR = COGNITIVE_QUEUES_DIR / "processing"
COGNITIVE_QUEUES_FAILED_DIR = COGNITIVE_QUEUES_DIR / "failed"
```

**`main.py` 的 `ensure_runtime_dirs()` 扩展：**

```python
if config.cognitive.enabled:
    cognitive_dirs = [
        COGNITIVE_DIR,
        COGNITIVE_CHROMADB_DIR,
        COGNITIVE_PROFILES_USERS_DIR,
        COGNITIVE_PROFILES_GROUPS_DIR,
        COGNITIVE_PROFILES_HISTORY_DIR,
        COGNITIVE_QUEUES_PENDING_DIR,
        COGNITIVE_QUEUES_PROCESSING_DIR,
        COGNITIVE_QUEUES_FAILED_DIR,
    ]
    for path in cognitive_dirs:
        ensure_dir(path)
```

**`CognitiveConfig` 路径字段改为引用常量：**

`CognitiveConfig` 的 `vector_store_path`、`queue_path`、`profiles_path` 默认值从 `utils/paths.py` 常量取，不硬编码字符串。各模块（JobQueue、ProfileStorage、VectorStore）构造时接收 `Path` 对象。

### 19.3 自动清理

**failed 队列清理**（复用 `utils/cache.py`）：

`cleanup_cache_dir` 签名为 keyword-only 参数：`cleanup_cache_dir(path, *, max_age_seconds=..., max_files=...)`。

在 `HistorianWorker` 的轮询循环中，每 N 轮（如 100 轮）调用一次：

```python
from Undefined.utils.cache import cleanup_cache_dir
cleanup_cache_dir(
    COGNITIVE_QUEUES_FAILED_DIR,
    max_age_seconds=config.failed_max_age_days * 86400,
    max_files=config.failed_max_files,
)
```

**侧写快照清理**（独立实现，不复用 `cleanup_cache_dir`）：

`cleanup_cache_dir` 只扫描单层目录的直接子文件，而侧写快照目录结构为 `history/{entity_type}/{entity_id}/{timestamp}.md`（嵌套目录），无法直接复用。

在 `ProfileStorage.write_profile()` 写入快照后，对该实体的 history 子目录做按数量清理：

```python
history_dir = self._history_dir / entity_type / entity_id
files = sorted(history_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
for old in files[self._revision_keep:]:
    old.unlink(missing_ok=True)
```

此逻辑按实体粒度执行，每次写入只清理当前实体的快照目录。

### 19.4 CognitiveConfig 路径字段同步更新

由于目录统一收纳到 `data/cognitive/`，§2.2 的 `CognitiveConfig` 默认值需同步调整：

```python
@dataclass
class CognitiveConfig:
    enabled: bool = True
    vector_store_path: str = "data/cognitive/chromadb"
    queue_path: str = "data/cognitive/queues"
    profiles_path: str = "data/cognitive/profiles"
    # ...其余字段不变
```

同时 §12.2 修改文件清单中 `config.toml.example` 的 `[cognitive.vector_store].path` 默认值也改为 `data/cognitive/chromadb`。

---

## 20. 文档：`docs/cognitive-memory.md`

新增文件：`docs/cognitive-memory.md`

与现有 `docs/multi-model.md`、`docs/callable.md` 同级，作为认知记忆系统的用户/开发者文档。

### 20.1 文档大纲

```markdown
# 认知记忆系统

## 概述
- 什么是认知记忆（事件记忆 + 用户/群侧写）
- 与旧 end_summaries 的区别（语义检索 vs 时序列表）
- 核心优势：跨会话记忆、语义召回、自动侧写、零前台延迟

## 快速启用
- config.toml 最小配置示例（[cognitive] + [models.embedding]）
- 依赖安装（chromadb）
- 验证方式（查看 data/cognitive/ 目录生成）

## 架构说明
- 前台零阻塞：end → 文件队列 → 后台史官
- 后台史官流水线：绝对化改写 → 正则闸门 → 向量入库 → 侧写合并
- 数据流图（简化版，文本 ASCII）

## 数据存储
- 事件记忆：ChromaDB events collection，metadata 字段说明
- 用户/群侧写：Markdown + YAML Frontmatter 格式示例
- 文件队列：pending → processing → complete/failed 三态
- 目录结构：data/cognitive/ 完整树形图

## 配置参考
- [cognitive] 全部配置项表格（字段、类型、默认值、说明）
- [models.embedding] 配置项表格（复用现有知识库配置）
- 热更新说明（哪些支持热更新，哪些需重启）

## AI 工具
- cognitive.search_events：参数、用途、示例
- cognitive.get_profile：参数、用途、示例
- cognitive.search_profiles：参数、用途、示例

## 运维
- 回退方式（三级：重启回退 → 侧写回滚 → 完整移除）
- 侧写快照与回滚操作
- failed 队列排查
- 日志关键字（historian、cognitive、闸门）

## FAQ
- Q: 开启后旧的 end_summaries 还能用吗？→ 双写过渡，可随时回退
- Q: 跨群会不会串记忆？→ ChromaDB where 硬过滤，不会
- Q: embedding 模型怎么选？→ 推荐 text-embedding-3-small，兼容 OpenAI API
```

---

## 21. README.md 改造

### 21.1 核心特性段新增

在现有"核心特性"列表中，删除旧的记忆相关描述（当前无独立条目，但 `EndSummaryStorage` 和 `MemoryStorage` 散见于架构图），新增认知记忆条目：

```markdown
- **认知记忆系统**：基于向量数据库的长期记忆架构，支持事件语义检索与用户/群聊自动侧写。后台史官异步处理，前台零延迟；支持重启回退与完整移除。详见 [认知记忆文档](docs/cognitive-memory.md)。
```

插入位置：在"多模型池"条目之后（两者都是高级特性）。

### 21.2 架构图更新

在 Mermaid 架构图的"存储与上下文层"子图中：

**替换：**
```
EndSummaryStorage["EndSummaryStorage<br/>短期总结存储<br/>[end_summary_storage.py]"]
```

**为：**
```
EndSummaryStorage["EndSummaryStorage<br/>短期总结存储<br/>[end_summary_storage.py]<br/>(cognitive 模式下由 CognitiveService 替代)"]
CognitiveService["CognitiveService<br/>认知记忆服务<br/>[cognitive/service.py]<br/>• 事件向量检索 • 用户/群侧写<br/>• 后台史官"]
```

新增连接线：
```
PromptBuilder -->|"注入"| CognitiveService
CognitiveService -->|"异步读写"| IOUtils
```

新增持久化层节点：
```
Dir_Cognitive["cognitive/<br/>• chromadb/ (向量库)<br/>• profiles/ (侧写)<br/>• queues/ (任务队列)"]
```

### 21.3 配置说明段新增

在"配置说明"的列表末尾（`[messages]` 之后、代理设置之前），新增：

```markdown
- **认知记忆（可选）**：`[cognitive]`
  - `[models.embedding]`：embedding 模型配置（复用知识库配置，api_url / api_key / model_name）
  - `enabled`：是否启用认知记忆系统（默认开启，embedding 未配置时自动降级）
  - 详细配置见 [认知记忆文档](docs/cognitive-memory.md)
```

### 21.4 文档与延伸阅读段新增

在现有列表末尾追加：

```markdown
- 认知记忆系统：[`docs/cognitive-memory.md`](docs/cognitive-memory.md)
```

### 21.5 目录结构段更新

在 `src/Undefined/` 树形图中新增 `cognitive/` 目录：

```
src/Undefined/
├── ai/            # AI 运行时
├── cognitive/     # 认知记忆系统（向量存储、史官、侧写、队列）
├── bilibili/      # B站视频
├── skills/        # 技能插件
│   ├── toolsets/
│   │   └── cognitive/  # 认知记忆主动工具（search_events / get_profile / search_profiles）
...
```

### 21.6 文件清单补充

§12.1 新增文件表追加：

| 文件 | 职责 |
|------|------|
| `docs/cognitive-memory.md` | 认知记忆系统文档 |

§12.2 修改文件表追加：

| 文件 | 改动 |
|------|------|
| `README.md` | 新增认知记忆特性、架构图更新、配置说明、文档链接 |
| `src/Undefined/utils/paths.py` | 新增 `COGNITIVE_*` 路径常量 |

---

## 22. 消灭硬编码：全部可配置化

### 22.1 硬编码清点

以下是 IMPL.md 各节中出现的硬编码数值，全部需提升为配置项：

| 来源 | 硬编码值 | 含义 |
|------|---------|------|
| §2.2 CognitiveConfig | `auto_top_k = 3` | 自动检索事件条数 |
| §2.2 CognitiveConfig | `tool_default_top_k = 12` | 主动工具默认检索条数 |
| §2.2 CognitiveConfig | `profile_top_k = 8` | 侧写搜索默认条数 |
| §2.2 CognitiveConfig | `rewrite_max_retry = 2` | 绝对化改写最大重试次数 |
| §2.2 CognitiveConfig | `profile_revision_keep = 5` | 侧写快照保留版本数 |
| §2.2 CognitiveConfig | `poll_interval_seconds = 1.0` | 史官轮询间隔 |
| §9.3 | `timeout_seconds=300` | 启动时恢复 stale 任务的超时 |
| §19.3 | `max_age_seconds=30天` | failed 队列文件最大保留天数 |
| §19.3 | `max_files=500` | failed 队列最大文件数 |
| §19.3 | `每 100 轮` | failed 队列清理检查间隔（轮次） |

### 22.2 CognitiveConfig 完整定义（替代 §2.2）

文件：`src/Undefined/config/models.py`

`EmbeddingModelConfig` 和 `RerankModelConfig` 已存在于 `config/models.py`，无需新增。仅新增 `CognitiveConfig`：

```python
@dataclass
class CognitiveConfig:
    """认知记忆系统配置"""
    enabled: bool = True

    # 路径（默认值引用 utils/paths.py 常量）
    vector_store_path: str = "data/cognitive/chromadb"
    queue_path: str = "data/cognitive/queues"
    profiles_path: str = "data/cognitive/profiles"

    # 检索
    auto_top_k: int = 3               # 每轮自动注入的事件条数
    tool_default_top_k: int = 12      # cognitive.search_events 默认 top_k
    profile_top_k: int = 8            # cognitive.search_profiles 默认 top_k

    # 史官
    rewrite_max_retry: int = 2        # 绝对化改写最大重试
    poll_interval_seconds: float = 1.0 # 史官轮询间隔（秒）
    stale_job_timeout_seconds: float = 300.0  # 启动恢复 stale 任务超时

    # 侧写
    profile_revision_keep: int = 5    # 每实体保留快照版本数

    # 清理
    failed_max_age_days: int = 30     # failed 队列文件保留天数
    failed_max_files: int = 500       # failed 队列最大文件数
    failed_cleanup_interval: int = 100 # 每 N 轮 poll 执行一次清理
```

### 22.3 `config.toml.example` 完整布局（替代 §2.4）

WebUI 自动发现 `config.toml.example` 中的所有段，按段名分组渲染表单。注释通过 `# zh:` 标签提取为字段提示。`api_key` 等敏感字段自动渲染为密码输入框。

以下为完整的 cognitive 配置段，独立成页（在 `config.toml.example` 末尾追加）：

```toml
# ============================================================
# 认知记忆系统（Cognitive Memory）
# 基于向量数据库的长期记忆，支持事件语义检索与用户/群侧写
# Vector-database-backed long-term memory with semantic event
# retrieval and automatic user/group profile management.
# 文档 / Docs: docs/cognitive-memory.md
# ============================================================

[cognitive]
# zh: 是否启用认知记忆系统（关闭时完全回退旧模式，支持热更新）
# en: Enable cognitive memory system (hot-reloadable; disabling falls back to legacy mode)
enabled = true

# 注意：Embedding/Rerank 模型配置复用现有 [models.embedding] 和 [models.rerank] 段，
# 无需在此重复配置。请确保 [models.embedding] 已正确配置。
# Note: Embedding/Rerank model config reuses existing [models.embedding] and [models.rerank].

[cognitive.vector_store]
# zh: ChromaDB 向量库存储路径
# en: ChromaDB persistent storage path
path = "data/cognitive/chromadb"

[cognitive.query]
# zh: 每轮对话自动检索并注入的相关事件条数（建议 3-5，过大会增加 prompt 长度）
# en: Number of relevant events auto-retrieved and injected per turn (3-5 recommended)
auto_top_k = 3
# zh: cognitive.search_events 工具默认返回条数
# en: Default top_k for the cognitive.search_events tool
tool_default_top_k = 12
# zh: cognitive.search_profiles 工具默认返回条数
# en: Default top_k for the cognitive.search_profiles tool
profile_top_k = 8

[cognitive.historian]
# zh: 绝对化改写最大重试次数（仍失败则降级写入并告警）
# en: Max retries for absolutization rewrite (falls back to degraded write on failure)
rewrite_max_retry = 2
# zh: 史官后台轮询队列的间隔（秒）
# en: Historian worker poll interval in seconds
poll_interval_seconds = 1.0
# zh: 启动时将 processing 目录中超时任务恢复到 pending 的超时阈值（秒）
# en: Timeout threshold (seconds) for recovering stale processing jobs on startup
stale_job_timeout_seconds = 300.0

[cognitive.profile]
# zh: 每个用户/群侧写保留的历史快照版本数
# en: Number of historical snapshot revisions to keep per user/group profile
revision_keep = 5
# zh: 侧写文件存储路径
# en: Profile files storage path
path = "data/cognitive/profiles"

[cognitive.queue]
# zh: 文件持久化队列存储路径
# en: File-based persistent queue storage path
path = "data/cognitive/queues"
# zh: failed 队列文件最大保留天数（超期自动清理）
# en: Maximum age in days for files in the failed queue before auto-cleanup
failed_max_age_days = 30
# zh: failed 队列最大文件数（超出时删除最旧的）
# en: Maximum number of files in the failed queue (oldest removed when exceeded)
failed_max_files = 500
# zh: 每 N 轮 poll 执行一次 failed 队列清理（0 表示禁用）
# en: Run failed queue cleanup every N poll iterations (0 to disable)
failed_cleanup_interval = 100
```

### 22.4 WebUI 兼容性

WebUI 自动发现机制（`toml_render.py` 的 `_build_order_map` 递归遍历）对新增段无需任何前端改动，但需注意：

| 要点 | 说明 |
|------|------|
| 段自动发现 | `config.toml.example` 中出现的段会自动渲染为表单分组，无需改前端代码 |
| 注释提示 | `# zh:` 格式的注释会被 `comment.py` 提取，显示为字段旁的帮助文本 |
| 敏感字段 | `api_key` 字段名匹配 `/api_key/i` 正则，自动渲染为密码输入框 |
| 布尔值 | `enabled` 渲染为 toggle 开关 |
| 数值 | `int` / `float` 渲染为 `<input type="number">` |
| 嵌套深度 | `[cognitive.historian]`、`[cognitive.queue]` 等二级嵌套正常渲染为子段 |
| 无 AOT | cognitive 配置不含 Array of Tables，无需修改 `AOT_PATHS` |

**唯一需要确认的点**：`config-form.js` 的 `createSubSubSection` 对三级嵌套（如 `cognitive.queue.failed_max_age_days`）的渲染。从代码看，二级嵌套（`cognitive.queue`）内的标量字段正常渲染，不存在三级嵌套问题。

---

## 23. 合理默认值与向后兼容

### 23.1 默认值设计依据

| 字段 | 默认值 | 依据 |
|------|--------|------|
| `cognitive.enabled` | `true` | 默认开启；`models.embedding` 未配置时启动会警告但不崩溃 |
| `query.auto_top_k` | `3` | 自动注入 prompt，过大增加 token 消耗；3 条足够提供上下文 |
| `query.tool_default_top_k` | `12` | 主动工具由 AI 主动调用，可接受更多结果；与 FINAL.md 基线一致 |
| `query.profile_top_k` | `8` | 侧写语义搜索，8 条覆盖常见场景 |
| `historian.rewrite_max_retry` | `2` | 超过 2 次说明 LLM 持续输出相对表达，降级写入更合理 |
| `historian.poll_interval_seconds` | `1.0` | 与 `QueueManager` 默认发车间隔一致，不过度占用 CPU |
| `historian.stale_job_timeout_seconds` | `300.0` | 5 分钟内未完成视为 stale；正常任务 < 30s，留足余量 |
| `profile.revision_keep` | `5` | 保留 5 版快照足够回滚；过多占用磁盘 |
| `queue.failed_max_age_days` | `30` | 30 天内的失败任务仍有排查价值 |
| `queue.failed_max_files` | `500` | 单目录 500 文件不影响 fs 性能 |
| `queue.failed_cleanup_interval` | `100` | 每 100 轮约 100 秒清理一次，开销极低 |

### 23.2 向后兼容策略

兼容性分三个维度：配置、工具参数、运行时行为。

#### 配置兼容

`config/loader.py` 解析 `[cognitive]` 段时，遵循现有 `_get_value` + `_coerce_*` 模式：若 `config.toml` 中完全没有 `[cognitive]` 段，所有字段取 `CognitiveConfig` 的 dataclass 默认值（`enabled=true`），不报错、不警告。

**降级检查位置**：在 `main.py` 初始化时（而非 `Config.load()` 中）执行。`CognitiveConfig.enabled` 保持配置文件的原始值不修改，`main.py` 额外判断 embedding 是否可用：

```python
# main.py 初始化时
cognitive_actually_enabled = config.cognitive.enabled
if cognitive_actually_enabled and (
    not config.embedding_model.api_url or not config.embedding_model.model_name
):
    logger.warning("[认知记忆] cognitive.enabled=true 但 models.embedding 未配置，自动降级禁用")
    cognitive_actually_enabled = False
```

这样 `config.cognitive.enabled` 始终反映用户意图，降级是运行时决策，不污染配置层。

#### end 工具参数兼容

| 调用方式 | 处理逻辑 | 结果 |
|---------|---------|------|
| 只传 `summary` | `action_summary = args.get("action_summary") or args.get("summary", "")` | 映射为 action_summary，new_info="" |
| 只传 `action_summary` | 直接使用 | 正常 |
| 同时传 `action_summary` + `summary` | `action_summary` 优先（`or` 短路） | 正常 |
| 都不传 | action_summary="" → 不入队，不写 end_summary | 与旧行为一致 |

旧版 `summary` 字段在 `config.json` 中保留（标注 `[过渡兼容]`），不删除，直到过渡期结束。

#### 运行时行为兼容

```
cognitive.enabled = false（手动关闭时）
    PromptBuilder → 走旧 end_summaries 注入分支（现有代码不变）
    end handler   → 只写 end_summary_storage（现有代码不变）
    cognitive 工具 → 返回 "认知记忆系统未启用"（不报错）
    HistorianWorker → 不启动

cognitive.enabled = true
    PromptBuilder → 走新 CognitiveService.build_context() 分支
    end handler   → 双写：end_summary_storage（旧）+ job_queue.enqueue（新）
    cognitive 工具 → 正常工作
    HistorianWorker → 启动轮询
```

双写的意义：过渡期内旧 `end_summaries.json` 始终有效，随时可以 `cognitive.enabled = false` 后重启切回旧模式，不丢任何数据。

#### Config 热更新兼容

`cognitive.enabled` **变更需重启**（与 `models.embedding.*`、`onebot.ws_url` 同级别）。原因：`false→true` 切换时底层组件（`JobQueue`、`VectorStore`、`ProfileStorage`、`HistorianWorker`）在 `enabled=false` 启动时不会被创建，无法热启动完整的 cognitive 系统。

以下查询参数支持热更新（通过 `config_getter()` 每次实时读取）：
- `cognitive.query.auto_top_k` / `tool_default_top_k` / `profile_top_k`
- `cognitive.historian.poll_interval_seconds`
- `cognitive.historian.rewrite_max_retry`

`models.embedding.*` / `models.rerank.*` 变更需重启（`ModelRequester` 按 `(api_url, api_key)` 缓存 `AsyncOpenAI` 客户端），与现有黑名单项处理方式一致。

---

## 24. 可选重排（Reranking）

### 24.1 设计

在向量检索之后、注入 prompt 之前插入重排步骤：

```
向量检索（top_k × candidate_multiplier 候选）
    ↓
Reranker.rerank(query, candidates)   ← 可选，未配置时跳过
    ↓
取前 top_k 条注入 prompt
```

**直接复用 `knowledge/reranker.py` 的 `Reranker` 类**，与知识库共享实例。`Reranker` 已实现：
- 队列+发车间隔（`queue_interval_seconds`）
- 通过 `ModelRequester.rerank()` → `RetrievalRequester.rerank()` 调用 `/rerank` 端点
- Token 用量自动记录（`call_type="rerank"`）
- 支持 Cohere/Jina 兼容格式，自动归一化响应

### 24.2 无需新增文件

**不新建 `cognitive/reranker.py`**。直接：

```python
from Undefined.knowledge import Reranker
```

复用现有 `RerankModelConfig`（`config/models.py`）和 `[models.rerank]` 配置段。

### 24.3 新增配置

仅在 `CognitiveConfig` 中新增一个字段控制候选倍数：

```python
@dataclass
class CognitiveConfig:
    # ...existing fields...
    rerank_candidate_multiplier: int = 3  # 向量检索候选数 = top_k × multiplier
```

`config.toml.example` 在 `[cognitive.query]` 段追加：

```toml
# zh: 重排候选倍数（启用重排时，先检索 top_k × multiplier 条再精排）
# en: Rerank candidate multiplier (fetch top_k × multiplier before reranking)
rerank_candidate_multiplier = 3
```

Reranker 的启用判断：`config.rerank_model.api_url` 和 `config.rerank_model.model_name` 均非空时自动启用（与知识库行为一致），无需额外 `enabled` 开关。

### 24.4 对现有模块的影响

| 模块 | 改动 |
|------|------|
| `config/models.py` | `CognitiveConfig` 新增 `rerank_candidate_multiplier` 字段 |
| `cognitive/vector_store.py` | `query_events` / `query_profiles` 接收可选 `reranker: Reranker \| None`；启用时先取 `top_k × multiplier` 候选再重排 |
| `cognitive/service.py` | 持有 `reranker: Reranker \| None`，传入查询方法 |
| `main.py` | 共享知识库的 `Reranker` 实例（若已创建） |

### 24.5 文件清单补充

无新增文件（复用 `knowledge/reranker.py`）。

§12.2 修改（追加）：

| 文件 | 改动 |
|------|------|
| `src/Undefined/cognitive/vector_store.py` | 支持可选重排 |
| `src/Undefined/cognitive/service.py` | 持有并传递 `Reranker` |
