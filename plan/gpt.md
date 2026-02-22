# Undefined 记忆架构重写方案（GPT 最终版）

版本：2026-02-21

## 1. 目标与硬约束（按你的要求落地）

1. `end_summary` 必须只包含两类信息：
   1. 做了什么（actions taken）
   2. 从会话中获取到的新信息（new information）
2. 每次记录在后台异步进程整理，不阻塞主对话回复。
3. 后台整理时必须消灭：
   1. 人称代词（我/你/他/她/它/这位等）
   2. 相对时间（刚才/今天/明天/上周）
   3. 相对地点（这里/那边/本地）
4. 事件记忆做 embedding，`ctx`（包含详细 `location/time` 字段）作为 metadata 存入数据库。
5. 每轮对话自动查询较小 `top_k`。
6. AI 可主动调用深度查询工具，默认更大 `top_k`，可修改。
7. 支持用户侧写：按 QQ 用户主动查询（传入 QQ 用户 + 问题），内容 embedding 化便于检索。
8. 支持群聊侧写：按群聊主动查询（传入群号 + 问题），内容 embedding 化便于检索。

## 2. 对 Gemini 初稿的结论

Gemini 的方向是对的：`向量事件流 + 异步史官 + 侧写` 是正确主线。

需要补强的关键点（这是我和 Claude 互辩时的重点）：

1. 仅“覆盖式 Markdown 侧写”会丢掉事实来源与冲突历史，容易被单次噪声覆盖。
2. 缺少“可靠异步”机制（重试、幂等、防重复写、失败补偿）。
3. 缺少“绝对化质量闸门”（检查代词/相对时间是否真的消除）。
4. 缺少“查询权限边界”与“跨群防串读”细则。
5. 缺少“从你当前代码平滑迁移”的步骤和验收指标。

## 3. 最终架构（Occam + 工程可用）

采用三层最小实现：

1. **事件层（Event Memory）**：向量库，追加写，不可变。
2. **侧写层（Profiles）**：结构化 JSON（源数据）+ Markdown（展示视图）。
3. **协调层（Async Historian）**：后台 worker，负责规范化、嵌入、入库、侧写合并。

推荐落地组合：

1. 单机优先（你现在最适合）：`SQLite + Chroma/LanceDB + asyncio background worker`。
2. 将来扩展：`PostgreSQL + Qdrant/LanceDB + Redis Streams`。

## 4. 数据模型（核心）

### 4.1 end_summary 新结构（强制两段）

```json
{
  "did_what": "2026-02-21T13:20:15+08:00，Undefined 在群 1017148870 中向 Null(1708213363) 发送了重写记忆架构的阶段性方案。",
  "new_info": "会话确认了新的记忆约束：end_summary 仅保留‘做了什么’与‘新信息’，并要求后台绝对化处理后再嵌入入库。"
}
```

说明：

1. 前台 `end` 工具可以仍收一个字符串，但后台必须转成上面的双字段；更推荐直接把 `end` 改成双字段参数。
2. 向量检索用 `canonical_text = did_what + "\n" + new_info`。

### 4.2 事件记忆表（向量 + metadata）

向量文档字段：

1. `doc_id`（幂等键，建议 `session_id:end_index`）
2. `canonical_text`
3. `embedding`

metadata（ctx）建议最小集合：

1. `event_time_utc`
2. `event_time_local`
3. `timezone`
4. `location_text`（绝对地点名）
5. `request_type`（private/group）
6. `qq_user_id`
7. `qq_group_id`
8. `sender_id`
9. `message_ids`（可追溯）
10. `source_request_id`
11. `schema_version`

### 4.3 侧写数据模型（用户/群聊统一）

**不要只存一份 Markdown 作为唯一真相**。建议：

1. `profile_state.json`（源数据，结构化）
2. `profile_view.md`（给模型注入与人工查看）

`profile_state.json` 示例：

```json
{
  "entity_type": "user",
  "entity_id": "1708213363",
  "updated_at": "2026-02-21T13:20:15+08:00",
  "facts": [
    {
      "key": "tech_stack",
      "value": ["Python", "QQ Bot"],
      "confidence": 0.86,
      "first_seen_at": "2026-02-20T10:00:00+08:00",
      "last_seen_at": "2026-02-21T13:20:15+08:00",
      "source_event_ids": ["evt_..."],
      "status": "active"
    }
  ],
  "preferences": [],
  "constraints": []
}
```

冲突处理规则（简化且稳定）：

1. 同 key 新值出现且置信度更高：覆盖旧值，旧值 `status=deprecated`。
2. 同 key 新值置信度低：先并存，等待后续证据。
3. 对“强时效字段”（当前项目/当前地点）加 TTL，过期自动降权。

## 5. 后台史官流程（关键闭环）

## 5.1 前台主流程（快）

1. 主 AI 调用 `end`。
2. 系统把本轮上下文打包成 `memory_job`（含会话片段、ctx、request_id）。
3. 仅做“入队成功确认”，立即返回，不等待整理完成。

## 5.2 史官 worker（慢但可靠）

1. 取任务（带重试计数）。
2. 生成双字段 `did_what/new_info`。
3. 绝对化改写（去代词/相对时间/相对地点）。
4. 质量闸门校验：
   1. 若含代词或相对表达，回炉重写一次。
   2. 二次失败则标记 `needs_review=true`，仍可入库但降权。
5. 生成 embedding。
6. 写入向量库（幂等 upsert）。
7. 更新用户/群聊侧写（merge）。
8. 记录审计日志（job_id、耗时、成功/失败原因）。

## 5.3 幂等与可靠性

1. 每个 job 有 `idempotency_key`。
2. 向量写入用 `doc_id` upsert，避免重复。
3. profile merge 记录 `last_applied_job_id` 防重复应用。
4. 失败任务指数退避重试，超过阈值进入 DLQ。

## 6. “去代词/去相对”执行策略

只靠一条 prompt 不够，推荐 **LLM 改写 + 规则校验**：

1. LLM 负责语义重写（最强）。
2. 规则校验器负责兜底：
   1. 代词词表检查（中英）
   2. 相对时间词表检查（今天/明天/刚刚/上周等）
   3. 相对地点词表检查（这里/那边/本地）
3. 时间绝对化：以 `ctx.event_time + timezone` 为基准解析。
4. 地点绝对化：优先 `ctx.location`，缺失时写“未知地点”，禁止保留“这里”。

## 7. 检索策略（自动小 K + 主动大 K）

## 7.1 自动注入（每轮）

1. 按当前会话作用域强过滤：
   1. 群聊：`qq_group_id == current_group_id`
   2. 私聊：`qq_user_id == current_user_id`
2. 默认 `top_k_small=3`（建议 2 条事件 + 1 条侧写片段）。
3. 注入内容上限字数，避免 prompt 爆炸。

## 7.2 主动工具查询

建议工具：

```python
def search_events(
    query: str,
    target_user_id: int | None = None,
    target_group_id: int | None = None,
    top_k: int = 12,
    time_from: str | None = None,
    time_to: str | None = None,
) -> list[dict]:
    ...


def search_profile(
    target_type: Literal["user", "group"],
    target_id: int,
    query: str,
    top_k: int = 8,
) -> dict:
    ...
```

规则：

1. `top_k` 默认主动查询更大（12），可由 AI 或系统调参。
2. `search_profile` 不只返回整篇 Markdown，可按 profile chunk embedding 返回相关段落。
3. 强制 metadata 过滤，避免跨群串记忆。

## 8. 用户侧写与群聊侧写（最终记录方案）

## 8.1 用户侧写建议字段

1. `identity`（稳定身份）
2. `tech_stack`
3. `current_projects`
4. `interaction_preferences`（沟通偏好）
5. `constraints`（禁忌、明确要求）
6. `timezone/location_hint`

## 8.2 群聊侧写建议字段

1. `group_purpose`
2. `group_rules`
3. `topic_preferences`
4. `sensitive_topics`
5. `group_jargon`
6. `maintenance_notes`

## 8.3 侧写 embedding 化

1. 把 profile 按 section chunk 化（如每段 200-400 tokens）。
2. 每段 embedding 后入 `profile_chunks` 集合。
3. 查询时按 `entity_type + entity_id` 过滤后做向量检索。

## 9. 与你当前仓库对接（最小改造路径）

当前关键点：

1. `src/Undefined/skills/tools/end/handler.py`
2. `src/Undefined/end_summary_storage.py`
3. `src/Undefined/ai/prompts.py`
4. `src/Undefined/memory.py`
5. `res/prompts/undefined.xml`
6. `res/prompts/undefined_nagaagent.xml`

分阶段改造：

1. **Phase 1（1-2天）**：改 `end_summary` 规范与 prompt，新增后台 job 队列（先本地 asyncio queue）。
2. **Phase 2（2-4天）**：引入向量库存储事件 + metadata filter + 自动小 `top_k` 注入。
3. **Phase 3（3-5天）**：实现 user/group profile merge + profile chunk embedding + 主动查询工具。
4. **Phase 4（1-2天）**：加幂等、重试、DLQ、监控指标与回归测试。

## 10. 验收指标（必须可量化）

1. 前台 `end` 平均耗时增加 < 30ms。
2. 史官任务成功率 > 99%。
3. 去代词/去相对表达通过率 > 98%。
4. 自动检索误召回（跨群）= 0。
5. 主动查询响应 p95 < 1.5s（本地部署可放宽）。

## 11. 风险与对策

1. **噪声覆盖侧写**：引入事实置信度 + deprecated 历史，不做盲覆盖。
2. **重复写入**：idempotency key + upsert。
3. **向量库不可用**：降级到仅 profile_state 检索，并标记 backlog 重放。
4. **绝对化失败**：规则校验 + 二次重写 + `needs_review` 降权。

## 12. 推荐的最终决策（给你拍板）

1. 保留你提出的“前台快 + 后台史官”总思路。
2. 将 end_summary 标准化为 `did_what/new_info` 双字段，这是本次重写的核心契约。
3. 事件流永远追加；侧写采用“结构化状态 + 可读视图”双轨，不建议只用 Markdown 覆盖。
4. 自动检索小 `top_k`，主动工具大 `top_k`，并且必须带 `user/group` 过滤。
5. 第一版先跑单机最小闭环（SQLite + Chroma/LanceDB），稳定后再升级到 Redis/Postgres 级别可靠队列。

## 13. 外部依据（用于和 Claude 互辩）

1. Chroma metadata filter 能力（支持过滤检索）：https://docs.trychroma.com/docs/querying-collections/metadata-filtering
2. Chroma query/get 过滤接口示例： https://docs.trychroma.com/docs/querying-collections/query-and-get
3. LanceDB 过滤与索引（where/filter + scalar/full text 等）：https://lancedb.github.io/lancedb/sql/
4. Qdrant 过滤检索（must/should/must_not）设计参考：https://qdrant.tech/documentation/concepts/filtering/
5. PostgreSQL `FOR UPDATE SKIP LOCKED`（并发 worker 抢任务常用基础）：https://www.postgresql.org/about/featurematrix/detail/skip-locked-clause/
6. Redis Streams + Consumer Groups（异步消费/ACK 机制）：https://redis.io/docs/latest/develop/data-types/streams/
7. `dateparser` 支持相对时间与多语言解析（含中文示例）：https://pypi.org/project/dateparser/
8. Duckling 支持时间维度抽取（time/duration 等）：https://github.com/facebook/duckling
9. 事务外盒（Transactional Outbox）模式参考：https://microservices.io/patterns/data/transactional-outbox.html
10. RAG 原始论文（top-k 检索范式来源）：https://arxiv.org/abs/2005.11401
11. Generative Agents 记忆检索与综合策略参考：https://arxiv.org/abs/2304.03442

