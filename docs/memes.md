# 全局表情包库 (Memes)

Undefined 平台自 3.3.0 版本起内置了强大的**全局表情包库**功能。该功能能够自动捕捉聊天中的图片、进行多模态模型判定与解析、并将其向量化归档，从而赋予 AI 在后续对话中“信手拈来”发送表情包的能力。

## 工作原理与两阶段处理管线

此功能核心是一个无阻塞的异步多模态处理管线（MemeWorker）：

1. **自动提取与去重**：
   收到图片消息时，系统后台自动将其投入去重队列，通过内容哈希判定该图是否已经入库。

2. **第一阶段 - 属性判定 (Judge)**：
   提交给视觉模型（通过 `judge_meme_image.txt` 提示词）分析图片本质。如果图片只是普通的自拍、系统截图或者无法表现梗（Meme）的内容，流程将在此终止。

3. **第二阶段 - 语义解析 (Describe)**：
   对于被判定为表情包的图片，模型会进一步（通过 `describe_meme_image.txt` 提示词）提取：
   - 图片的关键视觉元素与构图。
   - 隐喻、情感与适合的回复语境。
   - 高质量的搜索标签（Tags）。

4. **向量化与持久化**：
   提取出的结构化文本与标签被存入 SQLite (`MemeStore`)，并通过嵌入模型向量化后存入 ChromaDB (`MemeVectorStore`)。原图及其生成的预览图（如 GIF 抽帧）持久化存放至数据目录。

## AI 如何使用表情包？

存储与索引完成后，AI Agent 会通过内置的 `memes.*` 系列工具使用表情包：
- **`memes.search_memes`**：支持关键词检索（基于 SQLite）、语义检索（基于 ChromaDB 向量相似度）与混合检索（Hybrid）。AI 可借此根据当前对话的语境快速寻找最有梗的静态图或 GIF。
- **发送机制**：使用统一的图片 `uid` 进行索引。系统不仅提供了 `memes.send_meme_by_uid` 让 AI 一键发送表情包，还支持 AI 输出 `<pic uid="..."/>` 统一资源标签指令进行图文混排。

## 目录结构与配置

所有的持久化文件默认位于 `data/memes/` 下：
- `blobs/`：表情包原图文件。
- `previews/`：表情包预览图文件。
- `memes.sqlite3`：元数据及标签库。
- `chromadb/`：向量化知识库。
- `queues/`：异步任务队列缓存。

可通过 `config.toml` 的 `[memes]` 块开启、关闭及调整此功能：
```toml
[memes]
enabled = true                  # 是否启用
query_default_mode = "hybrid"   # 默认搜索策略：keyword / semantic / hybrid
```
更多细节请查阅 [配置文档](configuration.md#425-memes-表情包库)。

## 管理 API 集成

除了在聊天中自动捕获，你还可以通过前端 WebUI 或直接调用 Management API / Runtime API 对库内表情包进行增删改查。
包括：列出分页表情包库、删除、触发 `reanalyze`（重新判定解析）、`reindex`（强制重建向量缓存）。

* Management API 完整接口参阅 [Management API — Runtime 代理](management-api.md#6-runtime-代理)，Runtime API 直连接口参阅 [Runtime API — 表情包库](openapi.md#表情包库)。
