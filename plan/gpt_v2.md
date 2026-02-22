# Undefined 记忆架构重写方案 V2（GPT）

版本：2026-02-21

## 0. V2 结论（先拍板）

在 Gemini 版本基础上，V2 采用“**极简可落地 + 最小可靠性兜底**”路线：

1. 事件记忆：`ChromaDB(events)`，只追加。
2. 侧写：`Markdown + YAML Frontmatter` 单文件（用户/群聊各一份），避免双文件同步成本。
3. 异步：后台史官进程（queue + worker），前台 `end` 不阻塞。
4. 质量闸门：LLM 绝对化 + 代码规则拦截重写。
5. 检索：自动小 `top_k`（默认 3）+ 主动大 `top_k`（默认 12，可调）。
6. 隔离：默认按 `group_id/user_id` 强过滤，防串群。

这版保留 Gemini 的简洁，但补齐三件必须品：**幂等、可回滚、可观测**。

---

## 1. 对 Gemini 方案的吸收与修正

## 1.1 直接采纳

1. `end` 输入拆分为 `action_summary` + `new_info`。
2. Profile 采用 `Markdown + YAML Frontmatter`。
3. 事件与侧写都做 embedding 检索。
4. 史官异步处理，主链路只入队。

## 1.2 修正点（避免隐性风险）

1. **仅“暴力覆盖”会误伤**：改为“覆盖写入 + 自动保留最近 N 版快照（默认 5）”。
2. **只靠 request_id 做事件 ID 不稳**：同一请求可能多次 end 或重试，改为 `event_id = {request_id}:{end_seq}`。
3. **只写 Chroma 但无失败补偿**：增加本地 `jobs` 持久化目录与重试机制（不引入新基础设施）。

---

## 2. 数据契约（强约束）

## 2.1 end 工具入参（新）

```json
{
  "action_summary": "本轮做了什么",
  "new_info": "本轮得到的新信息，可为空",
  "force": false
}
```

兼容策略：

1. 若旧调用仍传 `summary`，后台先拆分：
   1. `action_summary = summary`
   2. `new_info = ""`
2. 过渡期保留 2-4 周，之后只接受双字段。

## 2.2 事件文档（Chroma `events`）

1. `id`: `event_id`（`request_id:end_seq`）
2. `document`: 绝对化后文本（由 `action_summary + new_info` 生成）
3. `metadata`:
   1. `request_id`
   2. `end_seq`
   3. `timestamp_utc`
   4. `timestamp_local`
   5. `timezone`
   6. `location_abs`
   7. `request_type` (`private`/`group`)
   8. `user_id`
   9. `group_id`
   10. `sender_id`
   11. `message_ids`
   12. `has_new_info` (bool)
   13. `schema_version` (`v2`)

## 2.3 侧写文件（单文件真相）

路径：

1. `data/profiles/users/{user_id}.md`
2. `data/profiles/groups/{group_id}.md`

格式：

```markdown
---
entity_type: user
entity_id: "1708213363"
name: "Null"
tags: ["Python", "QQ Bot", "Architecture"]
updated_at: "2026-02-21T13:20:15+08:00"
source_event_id: "req_xxx:1"
---
# 用户侧写
长期特征、偏好、约束、近期稳定目标。
```

覆盖策略：

1. 每次更新前，自动备份到 `data/profiles/_revisions/...`。
2. 保留最近 `N=5` 个修订版本。
3. 侧写全文 embedding 入 `profiles` 集合（metadata 包含 entity_type/entity_id）。

---

## 3. 后台史官流水线（最终）

## 3.1 主线程（前台）

1. `end` 被调用后，构建 `memory_job`。
2. `memory_job` 写入本地持久化队列目录（原子写入）。
3. 立即返回“对话已结束”，不等待史官处理。

## 3.2 史官 Worker

1. 取 job（状态 `pending` -> `processing`）。
2. LLM 生成绝对化 `did_what/new_info`。
3. 规则闸门校验（代词/相对时间/相对地点）。
4. 命中违规则回炉重写（最多 2 次）。
5. 生成事件 embedding 并 upsert 到 `events`。
6. 若 `new_info` 非空：
   1. 读取 user/group profile
   2. LLM merge 输出新 profile
   3. 快照备份 + 原子覆盖
   4. profile embedding upsert 到 `profiles`
7. job 标记 `done`，记录耗时与重试次数。

## 3.3 闸门规则（代码实现）

最小词表（首版）：

1. 代词：`我|你|他|她|它|他们|她们|它们|这位|那位`
2. 相对时间：`今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近`
3. 相对地点：`这里|那边|本地|当地|这儿|那儿`

校验通过条件：

1. 三类词均未命中，或命中但已被明确绝对化解释（白名单规则）。
2. 时间字段必须能解析为 ISO8601。

---

## 4. 检索机制（自动 + 主动）

## 4.1 自动检索（每轮注入）

1. 当前消息 embedding 查询 `events`，默认 `top_k=3`。
2. 强过滤：
   1. 群聊：`group_id == current_group_id`
   2. 私聊：`user_id == current_user_id`
3. 同时读取当前 user/group profile（全文或截断后注入）。

注入顺序：

1. `user_profile`
2. `group_profile`
3. `recent_relevant_events`

## 4.2 主动工具（给 AI 调用）

1. `cognitive.search_events(query, target_user_id=None, target_group_id=None, top_k=12, time_from=None, time_to=None)`
2. `cognitive.search_profiles(query, entity_type, entity_id, top_k=8)`
3. `cognitive.get_profile(entity_type, entity_id)`

默认策略：

1. 自动检索 `top_k_small=3`
2. 主动检索 `top_k_large=12`
3. `top_k` 可被系统配置覆盖。

---

## 5. 用户侧写 / 群聊侧写记录规范

## 5.1 用户侧写字段建议

1. `identity`
2. `tech_stack`
3. `working_style`
4. `interaction_preferences`
5. `hard_constraints`
6. `long_term_goals`

## 5.2 群聊侧写字段建议

1. `group_purpose`
2. `group_rules`
3. `tone_and_culture`
4. `common_topics`
5. `sensitive_topics`
6. `operation_notes`

## 5.3 更新触发条件

1. `new_info` 为空：默认不更新 profile。
2. `new_info` 非空且含长期特征：更新 profile。
3. 仅短期事件（一次性问题）不写入 profile，只写 events。

---

## 6. 与当前代码对接（精确到文件）

必改文件：

1. `src/Undefined/skills/tools/end/config.json`
2. `src/Undefined/skills/tools/end/handler.py`
3. `src/Undefined/end_summary_storage.py`
4. `src/Undefined/ai/prompts.py`
5. `src/Undefined/main.py`

新增文件建议：

1. `src/Undefined/memory_historian.py`（worker + queue）
2. `src/Undefined/memory_chroma.py`（events/profiles 封装）
3. `src/Undefined/profile_store.py`（frontmatter 读写 + revisions）
4. `src/Undefined/skills/toolsets/cognitive/...`（3 个主动工具）

配置新增（`config.toml`）：

1. `memory_historian_enabled = true`
2. `memory_auto_top_k = 3`
3. `memory_tool_top_k = 12`
4. `memory_profile_revision_keep = 5`
5. `memory_absolute_rewrite_max_retry = 2`

---

## 7. 分阶段实施计划（V2）

## Phase 1（接口与兼容，1-2 天）

1. end 入参升级（双字段 + 兼容 summary）。
2. prompt 规则更新（summary 仅两类信息）。
3. 先继续写 `end_summaries.json`，不破现网。

## Phase 2（史官异步 + Chroma 事件，2-4 天）

1. 上线 `historian_worker` 与本地持久化 job 队列。
2. 打通事件 absolute rewrite + embedding + upsert。
3. 自动小 `top_k` 注入替换旧 end_summaries 全量注入。

## Phase 3（侧写系统 + 主动工具，3-5 天）

1. user/group frontmatter profile。
2. profile revisions + embedding。
3. 上线 `cognitive.*` 主动查询工具。

## Phase 4（稳定性与验收，1-2 天）

1. 幂等/重试/DLQ。
2. 监控日志与统计指标。
3. 回归测试与迁移脚本。

---

## 8. 验收指标（量化）

1. 前台 `end` p95 延迟增加 < 30ms。
2. 史官任务成功率 > 99%。
3. 绝对化校验一次通过率 > 95%，最终通过率 > 99%。
4. 跨群误召回 = 0。
5. 自动注入 token 成本相对旧版下降 >= 40%（去掉全量摘要注入）。

---

## 9. 辩论要点（给 Claude 对齐）

1. 侧写文件格式：采用 Gemini 提议的 Frontmatter Markdown，但加版本快照防误覆盖。
2. 数据库复杂度：首版只引入 Chroma，不上额外 DB；可靠性用本地持久化队列补齐。
3. 反过度工程：不引入复杂置信度系统；只保留轻量回滚与事件追溯。
4. 工程底线：绝对化质量闸门、幂等 upsert、跨群强过滤三项不可删。

---

## 10. 最终建议（你可以直接拍板）

1. 立即按 V2 执行，先做 Phase 1+2（最快形成可用闭环）。
2. 侧写先上“覆盖 + revisions”，暂不做复杂评分。
3. 只要你确认，我下一步就按这个 V2 开始改代码。
