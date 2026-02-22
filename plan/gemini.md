### ⚖️ 第一部分：对 Claude 与 GPT 的架构裁决

在确定最终方案前，我们先定下几条架构铁律（拍板决断）：

1. **关于侧写（Profile）的存储格式：双双否决，引入「第三条路」**
   * **GPT 方案**：`state.json` + `view.md` 双文件，太繁琐，状态同步是噩梦。
   * **Claude 方案**：单文件 `JSON`。虽然简单，但对于大模型来说，阅读大量 JSON 转义字符会浪费 Token 且降低注意力。
   * **👉 我的裁决：采用 Markdown with YAML Frontmatter**。
     你的项目已经支持了 Anthropic Skills 的 `SKILL.md`（上面是 YAML，下面是 Markdown）。我们完全复用这个绝妙的结构！YAML 存结构化 tags 供检索，Markdown 存自然语言 summary 供大模型阅读。
2. **关于置信度与废弃历史（Confidence & Deprecated）：支持 Claude**
   * **GPT 方案**：搞置信度打分、留存历史废弃字段。这在 QQ Bot 场景下绝对是过度工程。
   * **👉 我的裁决：暴力覆盖**。侧写就是“当前最新切片”，旧的废话直接干掉。如果不小心覆盖错了怎么办？别忘了，我们的**事件流（Vector DB）**里存着完整历史，大不了 AI 调工具查一次。
3. **关于数据库选型：支持 Claude**
   * **GPT 方案**：SQLite + ChromaDB。
   * **👉 我的裁决：只需 ChromaDB**。Chroma 底层本来就是 SQLite，没必要自己再套一层关系型数据库。
4. **关于质量闸门（绝对化校验）：支持 GPT**
   * 大模型很容易“偷懒”，如果它总结时留了一句“他今天很高兴”，不拦截的话，这污染是永久的。**“LLM 提纯 + 纯代码正则表达式拦截重试”**是必须的工程底线。

---

### 🏆 第二部分：Undefined 认知记忆最终方案 (The Unified Edition)

这套方案只需新增 **ChromaDB** 一个外部依赖，其他全靠 Python 原生文件系统和异步队列实现。

#### 1. 数据模型（Data Schema）

**【修改 A：`end` 工具的入参契约】**
强制将原先单一的 `summary` 拆分为双字段，这是剥离动作与认知的关键：
*   `action_summary`: “做了什么 / 解决了什么”（如：编写了并发爬虫代码）
*   `new_info`: “获取到的新静态情报”（如：发现用户换 Mac 电脑了）。若无新情报可为空。

**【修改 B：事件记忆 - ChromaDB `events` 集合】**
*   **ID**: 直接使用上下文自带的 `request_id`（天然去重幂等）。
*   **Document**: `action_summary` 与 `new_info` 合并后，经由史官绝对化处理的纯文本。
*   **Embedding**: Document 的向量。
*   **Metadata**: `{"timestamp": 1771590000, "user_id": 1708213363, "group_id": 1017148870}`。

**【修改 C：实体侧写 - `data/profiles/users/{user_id}.md`】**
完美契合 LLM 阅读习惯的格式：
```markdown
---
user_id: 1708213363
name: "Null"
tags: ["Python", "全栈", "架构师", "极客"]
updated_at: 1771590000
---
# 用户侧写
Null 是 Undefined 项目的作者，目前在台湾。他偏好简洁、无冗余的代码架构（奥卡姆剃刀原则）。
最近的技术重心从纯 Python 转移到了大模型认知架构重构。
```
*(注：这篇 Markdown 的全文会进行 Embedding，存入 ChromaDB 的 `profiles` 集合，方便按语义找人。)*

---

#### 2. 后台史官异步流（The Historian Worker）

当主 AI 吐出 `end` 工具后，主流程直接给用户发消息结束。后台丢一个任务给 `historian_queue`。

**史官的 Pipeline（严密闭环）：**

1.  **绝对化提纯 (LLM)**：把 `action_summary` 和 `new_info` 扔给配置好的史官模型（便宜模型即可，带上当前绝对时间和地点）。
2.  **质量闸门 (Regex Check)**：Python 代码拦截。
    *   正则匹配：`r"\b(我|你|他|她|今天|昨天|明天|刚才|这里|那边)\b"`。
    *   若命中 -> 打回给 LLM 重写，Prompt 附加：“你在输出中使用了相对词‘今天’，请替换为具体日期”。
3.  **双写落盘**：
    *   获取 Embedding，`upsert` 进 ChromaDB 的 `events` 集合。
4.  **侧写更新 (LLM Merge)**：
    *   仅当 `new_info` 非空时触发。
    *   读取现有的 `user_{id}.md`。让 LLM 将 `new_info` 融入其中，输出新的完整 Markdown。
    *   覆写本地文件。

---

#### 3. 检索系统：潜意识与主动召回

**【潜意识注入】（每次发车时在 prompt 头部组装）**
*   **读文件（极速）**：根据当前 `user_id` 和 `group_id`，读取对应的 Profile Markdown。
*   **查向量（小 K）**：用用户最新的一句话，去 ChromaDB 查 `top_k=3`，**强制 `where={"group_id": current_group_id}`**。
*   **拼 Prompt**：
    ```xml
    <cognitive_context>
      <user_profile>... [Markdown内容] ...</user_profile>
      <group_profile>... [Markdown内容] ...</group_profile>
      <recent_relevant_events>
        - 2026-02-20: Undefined 为 Null 修复了并发 Bug。
        - 2026-02-18: Null 提出要引入 ChromaDB。
      </recent_relevant_events>
    </cognitive_context>
    ```

**【主动工具】（由大模型决定是否调用）**
新增 `skills/toolsets/cognitive/` 工具集：

1.  **`cognitive.search_events(query, target_user_id=None, time_from=None, top_k=15)`**
    *   大模型在潜意识不够用时，主动调用。
    *   支持传入 `time_from` 等参数，底层映射为 ChromaDB 的 metadata 过滤。
2.  **`cognitive.get_profile(target_id, type="user")`**
    *   当需要 @ 某个不在场的人，或者想了解另一个群时调用。

---

### 🚀 落地步骤建议 (The Roadmap)

这份方案对你目前的 `Undefined` 项目改动是完全可控的，建议按以下三步走：

*   **Step 1（接口契约层）**：先改 `skills/tools/end/config.json`，把单一字符串拆成 `action_summary` 和 `new_info`。跑几天看看大模型填这两个字段的质量。
*   **Step 2（史官守护进程）**：引入 `chromadb`。在 `ai_client` 启动时，拉起一个 `historian_worker` 的异步死循环任务，监听 `end` 触发的队列，完成绝对化和向量入库。
*   **Step 3（检索与侧写）**：在 `prompts.py` 组装前加入 ChromaDB 的查询，并实现侧写的覆写逻辑与两个新 Tool。

