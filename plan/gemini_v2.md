这不仅是一次架构选型，更是一次**工程思维的升华**。

我仔细审阅了 **Claude V2（极致简约派）** 和 **GPT V2（工程稳健派）** 的方案。它们在核心理念上已经高度统一，但在**数据持久性**和**容错机制**上存在分歧。

---

# 🏛️ Undefined 认知记忆架构 V2

**核心哲学**：
1.  **前台极速**：主对话流程只做“读”，不做“写/算”。
2.  **后台稳健**：引入**文件级持久化队列**（File-based Queue），确保即使 Bot 崩溃/重启，记忆任务也不丢失。
3.  **存储双轨**：
    *   **事件流 (Events)** -> ChromaDB (不可变，只追加)
    *   **侧写 (Profiles)** -> Markdown + YAML (可变，快照回滚)

---

## 1. 最终裁决：核心争议点定案

| 争议点 | 最终决策 | 理由 |
| :--- | :--- | :--- |
| **侧写格式** | **Markdown + YAML Frontmatter** | JSON 对 LLM 阅读不友好（转义符干扰）；Markdown 读取后可直接作为 String 注入 Prompt，无需二次格式化。 |
| **侧写保护** | **覆盖写入 + 本地 N 版快照** | 既避免了 GPT 复杂的置信度计算，又解决了 Claude“误覆盖无法挽回”的风险。简单有效。 |
| **异步机制** | **本地文件队列 (`data/queues/`)** | 拒绝纯内存 `asyncio.create_task`（进程挂了数据就丢了）；也拒绝 Redis。用文件做队列最适合单机 Bot。 |
| **质量闸门** | **LLM 改写 + 正则代码拦截** | 双保险。代码必须死守“去代词”的底线。 |
| **ID 策略** | **`request_id`** | 足够了。Undefined 的架构是一问一答，一次请求只产生一个 `end`。 |

---

## 2. 数据契约（Data Contracts）

### 2.1 工具：`end` (接口升级)
必须强制分离“动作”与“认知”。

```json
{
  "name": "end",
  "parameters": {
    "action_summary": "本轮具体做了什么、回复了什么（用于构建事件流）",
    "new_info": "本轮获取到的、值得永久记录的新情报（用于更新侧写）。若无则留空。",
    "force": false
  }
}
```

### 2.2 存储 A：事件流 (ChromaDB `events` Collection)
*   **Document**: 经过史官绝对化处理后的文本。
*   **Metadata**: 包含全量上下文，用于硬过滤。
    *   `timestamp`: 1771590000
    *   `group_id`: 1017148870 (私聊为 0)
    *   `user_id`: 1708213363
    *   `tags`: "python, concurrency" (可选，由 LLM 生成)

### 2.3 存储 B：侧写 (Markdown Profile)
路径：`data/profiles/users/{user_id}.md` (群聊同理)

```markdown
---
updated_at: "2026-02-21T14:30:00"
tags: ["Python", "全栈", "极客"]
---
# Null 的侧写
Undefined 项目作者。技术栈主修 Python/TypeScript，近期转向 Rust。
偏好奥卡姆剃刀原则，不喜欢过度设计的架构。
```
*   **优势**：读取时，直接把 `---` 下面的内容切出来塞进 Prompt，省时省力。

---

## 3. 架构流程图 (The Pipeline)

### ✅ 前台主流程 (Fast Path)
1.  **收到消息**：`handle_message`。
2.  **潜意识注入**：
    *   读取 `data/profiles/users/{uid}.md` (IO读取，极快)。
    *   ChromaDB 查询 `Top-3` 相关事件 (向量计算，快)。
    *   组装 Prompt 发给主模型。
3.  **模型回复**：调用 `end(action_summary, new_info)`。
4.  **任务落盘**：将 `memory_job` JSON 写入 `data/queues/pending/{uuid}.json`。
5.  **立即响应**：Bot 发送消息并结束。用户无感知。

### ✅ 后台史官 Worker (Robust Path)
一个死循环的异步 Worker，不断扫描 `data/queues/pending/`。

1.  **取任务**：读取并移动文件到 `processing/` 目录。
2.  **绝对化 (Absolutization)**：
    *   调用廉价模型（如 `glm-4-flash` 或 `gpt-4o-mini`）。
    *   Input: `action_summary` + `ctx (time, location, user)`。
    *   Prompt: "消灭代词，替换为绝对名词"。
3.  **质量闸门 (The Gate)**：
    *   运行 Python 正则：`if re.search(r"(今天|明天|我|你|他)", text):`
    *   命中 -> **驳回重写** (最多 2 次)。
    *   通过 -> 继续。
4.  **双写 (Dual Write)**：
    *   **事件**：Embedding -> Upsert ChromaDB。
    *   **侧写** (仅当 `new_info` 有值)：
        *   读旧 Markdown -> LLM Merge -> 生成新 Markdown。
        *   **快照**：把旧文件复制到 `data/profiles/history/`。
        *   **覆盖**：写入新文件。
5.  **完成**：删除任务文件。

---

## 4. 关键代码实现指引

### 4.1 史官 Prompt (必须狠)

```markdown
# 史官指令
你是一个冷酷的记录者。你的任务是将聊天摘要转化为【绝对时空坐标】的档案。

【输入元数据】
时间：{ctx.timestamp_iso}
地点：{ctx.location} (默认为 网络空间)
主角：{ctx.user_name} ({ctx.user_id})

【原始摘要】
{action_summary} {new_info}

【处理规则】
1. **消灭相对词**：严禁出现“今天”、“刚才”、“用户”、“我”。必须替换为“2026年2月21日”、“Null”、“Undefined”。
2. **第三人称**：永远使用第三人称陈述句。
3. **合并输出**：将动作和新信息合并为一段流畅的文本。

【错误示例】
❌ 我帮他修复了代码，他很高兴。
【正确示例】
✅ 2026-02-21，Undefined 协助 Null 修复了 Python 并发代码，Null 表达了满意。
```

### 4.2 目录结构规范

```bash
data/
├── chromadb/          # 向量数据库本体
├── profiles/          # 侧写 Markdown
│   ├── users/
│   ├── groups/
│   └── history/       # 侧写快照 (回滚用)
└── queues/            # 文件级持久化队列
    ├── pending/       # 待处理任务
    ├── processing/    # 处理中 (防崩溃)
    └── failed/        # 也就是 Dead Letter Queue
```

---

## 5. 迁移与落地计划

**第一阶段：无痛热身 (Day 1)**
1.  修改 `end` 工具的 `config.json`，支持双字段。
2.  在 `handler.py` 里写兼容逻辑：如果是旧参数，自动填入 `action_summary`。
3.  **此时不开启后台 Worker**，先让主模型适应新参数，看看日志里的 `new_info` 填得对不对。

**第二阶段：史官上岗 (Day 2)**
1.  引入 `chromadb`。
2.  实现 `HistorianWorker` 类，启动时后台运行。
3.  实现文件队列逻辑。
4.  跑通 **"聊天 -> end -> 落文件 -> Worker读取 -> 写入Chroma"** 流程。

**第三阶段：潜意识觉醒 (Day 3)**
1.  修改 `prompts.py`。
2.  加入 ChromaDB 的 Top-3 查询。
3.  加入 Profile Markdown 的读取注入。
4.  **此时，Undefined 将正式拥有长时记忆。**

**第四阶段：主动能力 (Day 4)**
1.  实现 `search_events` 和 `get_profile` 工具。
2.  让 AI 学会去翻旧账。

---

### 💡 为什么这版是最终答案？

它遵循了**工程学的最大原则：把复杂性留在后台，把确定性留给前台。**

*   前台（用户感知的）极其简单：读文件、查向量、发消息。
*   后台（处理脏活累活）：重试、正则校验、快照备份、向量化。

