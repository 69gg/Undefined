# Undefined 记忆架构最终方案（FINAL）

版本：2026-02-21
来源：综合 `plan/claude_final.md` + `plan/gemini_v2.md`（并吸收 GPT v2 的工程约束）| 综合 Claude / GPT / Gemini 三方研讨

---

## 0. 最终拍板（不可再摇摆）

1. `end` 记忆输入采用双字段语义：`action_summary`（本轮做了什么）+ `new_info`（针对当前新消息抽取的一条新记忆），两者均可为空。
2. 前台只负责入队，后台史官异步整理；主回复链路绝不等待记忆写入。
3. 史官必须做绝对化：消灭代词、相对时间、相对地点。
4. 事件记忆存 ChromaDB（`events`），并写入完整 metadata（含 location/time）。
5. 自动检索用小 `top_k`（默认 3）；主动工具默认大 `top_k`（默认 12，可改）。
6. 用户/群聊侧写采用 `Markdown + YAML Frontmatter`，并做 embedding 便于语义检索。
7. 侧写更新采用“覆盖写 + 本地快照回滚（默认保留 5 版）”。
8. 单机场景使用**文件级持久化队列**（`pending/processing/failed`），确保进程崩溃不丢任务。

---

## 1. 争议裁决（最终结论）

1. 侧写格式：采用 **Markdown + YAML Frontmatter**。
理由：LLM 读写友好，注入 prompt 直接可用；同时保留 YAML 元数据供程序过滤。
2. 存储选型：采用 **ChromaDB 单一向量库**（不额外引入 SQL 主库）。
理由：当前场景单机、快速迭代，复杂度最低。
3. 可靠性：采用 **文件持久化队列**，不使用纯 `asyncio.create_task` 内存队列。
理由：Bot 异常重启后可恢复任务。
4. 置信度系统：**首版不做**。
理由：先保证闭环可用；风险由“事件全量可追溯 + 侧写快照回滚”覆盖。
5. 事件 ID：采用 `event_id = {request_id}:{end_seq}`。
理由：比单 request_id 更稳，兼容重试和极端重复调用。

---

## 2. 数据契约（必须实现）

## 2.1 `end` 工具新参数

```json
{
  "action_summary": "本轮做了什么",
  "new_info": "针对当前新消息提取的一条新记忆（可空）",
  "force": false
}
```

约束：

1. `end` 允许空调用（两字段都为空）用于仅结束对话，不产生日志入队。
2. `action_summary` 仅记录 AI 本轮实际动作，保持短句。
3. `new_info` 每条新消息最多 1 条，提取不到则留空，不复述历史已知信息。

兼容策略：

1. 过渡期接受旧 `summary`。
2. 若仅有 `summary`：映射为 `action_summary=summary`，`new_info=""`。
3. 过渡期结束后删除旧参数。

## 2.2 事件集合（Chroma: `events`）

1. `id`: `event_id`（`request_id:end_seq`）
2. `document`: 绝对化后的 `canonical_text`
3. `metadata`:
   1. `request_id`
   2. `end_seq`
   3. `timestamp_utc`
   4. `timestamp_local`
   5. `timezone`
   6. `location_abs`
   7. `request_type` (`group`/`private`)
   8. `user_id`
   9. `group_id`
   10. `sender_id`
   11. `message_ids`
   12. `has_new_info`
   13. `schema_version` (`final_v1`)

## 2.3 侧写文件

路径：

1. `data/profiles/users/{user_id}.md`
2. `data/profiles/groups/{group_id}.md`

模板：

```markdown
---
entity_type: user
entity_id: "1708213363"
name: "Null"
tags: ["Python", "QQ Bot", "Architecture"]
updated_at: "2026-02-21T14:30:00+08:00"
source_event_id: "req_xxx:1"
---
# 用户侧写
长期稳定特征、偏好、约束、近期主线目标。
```

快照：

1. 更新前备份到 `data/profiles/history/...`
2. 每实体保留最近 5 版（可配置）

## 2.4 侧写向量集合（Chroma: `profiles`）

1. `id`: `{entity_type}:{entity_id}`
2. `document`: 侧写正文（Markdown 正文部分）
3. `metadata`: `entity_type`, `entity_id`, `updated_at`, `tags`

---

## 3. 后台史官流程（标准流水线）

1. 前台 `end` 调用后，若 `action_summary`/`new_info` 任一非空，则落盘 `memory_job` 到 `data/queues/pending/{job_id}.json`。
2. Worker 从 `pending` 原子移动到 `processing` 后处理。
3. LLM 绝对化改写：生成 `did_what/new_info/canonical_text`。
4. 正则闸门检查：
   1. 代词：`我|你|他|她|它|他们|她们|它们|这位|那位`
   2. 相对时间：`今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近`
   3. 相对地点：`这里|那边|本地|当地|这儿|那儿`
5. 命中违规则回炉重写，最多 2 次；仍失败则降级写入并打告警。
6. 事件 embedding + upsert 到 `events`（允许按 group/sender 等视角生成多条事件记录）。
7. 若 `new_info` 非空：合并并覆盖 user/group profile，写快照，再更新 `profiles` embedding。
8. 成功后删除 `processing` 任务；失败进入 `failed/`。

---

## 4. 检索机制（双轨）

## 4.1 自动检索（每轮）

1. 查询 `events`：默认 `top_k=3`。
2. 强过滤：
   1. 群聊：`group_id == current_group_id`
   2. 私聊：`user_id == current_user_id`
3. 同步注入：当前用户侧写 + 当前群侧写 + 相关事件摘要。

## 4.2 主动工具

1. `cognitive.search_events(query, target_user_id=None, target_group_id=None, top_k=12, time_from=None, time_to=None)`
2. `cognitive.get_profile(entity_type, entity_id)`
3. `cognitive.search_profiles(query, entity_type, entity_id, top_k=8)`

---

## 5. 代码改造清单（按文件）

必改：

1. `src/Undefined/skills/tools/end/config.json`
2. `src/Undefined/skills/tools/end/handler.py`
3. `src/Undefined/ai/prompts.py`
4. `src/Undefined/main.py`
5. `res/prompts/undefined.xml`
6. `res/prompts/undefined_nagaagent.xml`

新增：

1. `src/Undefined/cognitive/vector_store.py`
2. `src/Undefined/cognitive/embedding.py`
3. `src/Undefined/cognitive/historian.py`
4. `src/Undefined/cognitive/profile_storage.py`
5. `src/Undefined/cognitive/job_queue.py`
6. `src/Undefined/skills/toolsets/cognitive/search_events/handler.py`
7. `src/Undefined/skills/toolsets/cognitive/get_profile/handler.py`
8. `src/Undefined/skills/toolsets/cognitive/search_profiles/handler.py`

目录：

1. `data/chromadb/`
2. `data/profiles/users/`
3. `data/profiles/groups/`
4. `data/profiles/history/`
5. `data/queues/pending/`
6. `data/queues/processing/`
7. `data/queues/failed/`

---

## 6. 配置项（新增）

```toml
[cognitive]
enabled = true

[cognitive.embedding]
model = "text-embedding-3-small"
api_url = ""
api_key = ""

[cognitive.vector_store]
path = "data/chromadb"

[cognitive.query]
auto_top_k = 3
tool_default_top_k = 12

[cognitive.historian]
rewrite_max_retry = 2
profile_revision_keep = 5
poll_interval_seconds = 1.0
```

---

## 7. 实施计划（最终版）

## Phase 1（1-2 天）

1. end 参数升级（双字段 + 兼容 summary）。
2. prompt 规则改造（明确 action_summary/new_info 语义）。
3. 维持旧逻辑可运行。

## Phase 2（2-4 天）

1. 接入 ChromaDB 与 embedding。
2. 上线文件队列 + historian worker。
3. 跑通“对话->落队列->写 events”。

## Phase 3（3-5 天）

1. 上线 user/group profile 合并与快照。
2. 上线 `profiles` 向量检索。
3. 上线 `cognitive.*` 主动工具。

## Phase 4（1-2 天）

1. 监控与告警（失败率、重试次数、处理时延）。
2. 迁移旧 `end_summaries.json` 到 `events`。
3. 回归测试与灰度开关验证。

---

## 8. 验收标准

1. 前台 `end` 延迟增加 p95 < 30ms。
2. 史官任务成功率 > 99%。
3. 绝对化闸门最终通过率 > 99%。
4. 跨群误召回 = 0。
5. 关闭 `cognitive.enabled` 后可完整回退旧模式。

---

## 9. 本版刻意不做（防过度设计）

1. 不做复杂 confidence/deprecated 体系。
2. 不引入 Redis/Kafka/PostgreSQL。
3. 不做多级 profile chunk 策略（先全文，后续再优化）。

---

## 10. 最终执行口令

按本 `FINAL` 文档执行，后续讨论以本文件为唯一基线；若有新分歧，以“是否破坏前台低延迟与单机可维护性”为第一裁决标准。
