# 本地知识库

## 功能概述

将本地纯文本文件向量化后存入 ChromaDB，AI 可通过三个工具查询：

| 工具 | 说明 |
|------|------|
| `knowledge_list` | 列出所有可用知识库及 `intro.md` 简介 |
| `knowledge_text_search` | 关键词搜索原始文本 |
| `knowledge_semantic_search` | 语义相似度搜索 |

## 目录结构

```
knowledge/                        # 项目根目录，仅存数据
└── {知识库名}/
    ├── intro.md                  # 必填：给 AI 看的知识库简介
    ├── texts/                    # 必填：原始文本目录（支持子目录）
    ├── chroma/                   # ChromaDB 向量库（自动生成）
    └── .manifest.json            # 文件 hash 记录（自动生成）
```

`knowledge/` 下不放代码，只有数据文件。`intro.md` 用于让 AI 先理解“这个库讲什么”，再决定是否调用搜索工具。系统会自动递归扫描 `texts/` 下的常见纯文本文件（如 `md/txt/html/htm` 等），并忽略 `chroma/`、`.manifest.json`、`intro.md`。`chroma/` 和 `.manifest.json` 已加入 `.gitignore`。

## 快速开始

**1. 配置 `config.toml`**

```toml
[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "text-embedding-3-small"
queue_interval_seconds = 1.0      # 发车间隔（秒）
dimensions = 512                  # 向量维度（可选，0或不填则使用模型默认值）
query_instruction = ""            # 查询端指令前缀（Qwen3-Embedding 等模型需要）
document_instruction = ""         # 文档端指令前缀（E5 系列需要 "passage: "）

[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "text-rerank-001"
queue_interval_seconds = 1.0      # 发车间隔（秒）
query_instruction = ""            # 查询端指令前缀（部分重排模型需要）

[knowledge]
enabled = true
base_dir = "knowledge"            # 知识库根目录
auto_scan = true                  # 定期扫描文本变更
auto_embed = true                 # 发现变更自动嵌入
scan_interval = 60                # 扫描间隔（秒）
embed_batch_size = 64             # 每批嵌入块数
chunk_size = 10                   # 每个向量块包含的行数（滑动窗口大小）
chunk_overlap = 2                 # 相邻块重叠的行数
default_top_k = 5                 # 语义搜索默认召回数
enable_rerank = true              # 是否启用重排（可被 tool 参数覆盖）
rerank_top_k = 3                  # 重排后返回数量（必须小于 default_top_k）
```

**2. 准备知识库目录（含 `intro.md`）**

```
knowledge/
└── my_docs/
    ├── intro.md
    └── texts/
        ├── faq.txt
        ├── manual.md
        └── docs/
            └── policy.html
```

`intro.md` 示例（简洁、可判别）：

```md
这个知识库用于心脏医学研究，包含冠心病、心律失常、心力衰竭相关文献摘要与术语说明。
```

**3. 启动机器人**

启动后自动扫描并嵌入，日志中会出现：

```
[知识库] 初始化完成: base_dir=knowledge
[知识库] kb=my_docs file=texts/faq.txt lines=42
```

## 工具用法

### knowledge_list

列出知识库（结构化紧凑输出）。建议先调用它，再根据简介选择 `knowledge_base`。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `only_ready` | boolean | | 是否仅返回已配置 `intro.md` 的知识库，默认 `true` |
| `include_intro` | boolean | | 是否返回简介，默认 `true` |
| `include_has_intro` | boolean | | 是否返回 `has_intro` 字段，默认 `false` |
| `intro_max_chars` | integer | | 每个简介最大字符数，默认 `120` |
| `max_items` | integer | | 最多返回知识库条目，默认 `50` |
| `name_keyword` | string | | 按名称关键词过滤（不区分大小写） |

```json
{"ok":true,"count":1,"truncated":false,"items":[{"name":"cardio_research","intro":"心脏医学研究资料"}]}
```

### knowledge_text_search

在原始文本中按关键词搜索（结构化紧凑输出）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | string | ✓ | 知识库名称 |
| `keyword` | string | ✓ | 搜索关键词 |
| `max_lines` | integer | | 最多返回行数，默认 20 |
| `max_chars` | integer | | 搜索阶段总字符上限，默认 2000 |
| `max_chars_per_item` | integer | | 每条结果最大字符数，默认 180 |
| `case_sensitive` | boolean | | 是否大小写敏感，默认 `false` |
| `source_keyword` | string | | 按 `source` 路径关键词过滤 |
| `include_source` | boolean | | 是否输出 `source`，默认 `true` |
| `include_line` | boolean | | 是否输出 `line`，默认 `true` |

返回示例：

```json
{"ok":true,"knowledge_base":"my_docs","keyword":"重置密码","count":2,"items":[{"source":"texts/faq.txt","line":12,"text":"如何重置密码？"},{"source":"texts/manual.txt","line":5,"text":"密码长度不少于8位"}]}
```

### knowledge_semantic_search

通过嵌入向量计算语义相似度，返回结构化结果。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | string | ✓ | 知识库名称 |
| `query` | string | ✓ | 查询文本 |
| `top_k` | integer | | 语义召回数量，默认取配置值 |
| `enable_rerank` | boolean | | 是否启用重排；不传则使用配置默认值 |
| `rerank_top_k` | integer | | 重排返回数量，需小于语义召回数量 |
| `min_relevance` | number | | 相关度阈值（0-1），默认 0 |
| `source_keyword` | string | | 按 `source` 路径关键词过滤 |
| `max_chars_per_item` | integer | | 每条结果最大字符数，默认 220 |
| `include_rerank_score` | boolean | | 是否输出 `rerank_score`，默认 `true` |
| `deduplicate` | boolean | | 是否按 `source+text` 去重，默认 `true` |

返回示例：

```json
{"ok":true,"knowledge_base":"my_docs","query":"怎么重置密码","count":2,"items":[{"source":"texts/faq.txt","text":"重置密码需要验证手机号","relevance":0.91,"rerank_score":0.981245},{"source":"texts/faq.txt","text":"忘记密码可联系客服","relevance":0.87,"rerank_score":0.9123}]}
```

### 参数优先级与约束

`knowledge_semantic_search` 参数优先级：

1. tool 调用参数（`top_k` / `enable_rerank` / `rerank_top_k`）
2. `config.toml` 中 `[knowledge]` 默认值

约束规则：

- `top_k`、`rerank_top_k` 必须为正整数
- `rerank_top_k` 必须小于本次语义召回数量（即本次 `top_k` 生效值）
- 当约束不满足时，系统会自动降级：缩小 `rerank_top_k` 或禁用重排（并输出日志告警）

## 工作原理

### 文本切分

每个文本文件（如 `.txt/.md/.html/.htm`）先按行切分并忽略空行，再用**滑动窗口**合并为向量块：

```
原始行: [l1, l2, l3, l4, l5, l6, l7]
chunk_size=4, chunk_overlap=1 → step=3

块1: l1\nl2\nl3\nl4
块2: l4\nl5\nl6\nl7
```

- `chunk_size`：每块包含的行数（默认 10）
- `chunk_overlap`：相邻块重叠的行数（默认 2），保证语义连续性

### 增量嵌入

`.manifest.json` 记录每个文件的 SHA256 hash。扫描时只对新增或内容变更的文件重新嵌入，未变更的文件跳过。

### 站台/发车队列

嵌入与重排请求都通过内置队列串行发送，按各自 `queue_interval_seconds` 控制发车间隔，避免超出 API 速率限制。多行文本按 `embed_batch_size` 分批，每批一次 API 调用。

```
texts → split_lines → [batch 1, batch 2, ...] → Queue → API (间隔发车)
```

### 两阶段检索（可选重排）

语义检索支持两阶段：

1. 向量召回：先按相似度召回 `top_k` 条
2. 重排：若启用重排，再对召回结果执行 rerank，最终返回 `rerank_top_k` 条

重排开启条件：

- `knowledge.enable_rerank = true` 或 tool 参数 `enable_rerank=true`
- `models.rerank` 配置完整
- `rerank_top_k < 语义召回数量`

若你的重排模型要求指令前缀（例如 `Instruct: ...\nQuery: `），可配置 `models.rerank.query_instruction`，系统会在重排请求时自动拼接到 `query` 前。

### 统一 OpenAI 请求层与 Token 统计

知识库检索中的嵌入和重排都走统一的 OpenAI 请求层（OpenAI SDK）：

- 嵌入：`/v1/embeddings`
- 重排：`/v1/rerank`

这样做的好处：

- 统一复用连接池、base_url 兼容处理、错误处理逻辑
- 便于后续扩展新的检索相关能力
- 统一记录 token 使用，方便 `/stats` 统计

`/stats` 中可看到新增调用类型：

- `embedding`
- `rerank`

> 若上游响应缺失 usage 字段，系统会回退到本地估算，确保统计口径连续可用。

### 向量存储

使用 ChromaDB 的 cosine 距离度量。每行内容的 SHA256 前 16 位作为 ID，重复内容自动去重（upsert）。

## 嵌入模型适配

不同嵌入模型对输入格式的要求不同，主要区别在于**查询端是否需要拼接指令前缀**。

### query_instruction 与 document_instruction 说明

部分模型（如 Qwen3-Embedding、E5、BGE、Instructor 系列）在训练时采用了带指令的对比学习，Query 和 Document 的向量空间是分开优化的。对这类模型，需要在文本前拼接对应指令，否则检索效果会大幅下降。

| 配置项 | 作用时机 | 说明 |
|--------|---------|------|
| `query_instruction` | 语义搜索时，拼接到查询文本前 | Qwen3、BGE 等只有 Query 端需要 |
| `document_instruction` | 嵌入文档时，拼接到每行文本前 | E5 系列 Document 端也需要前缀 |

两者默认为空，不填则不拼接。

### 各模型配置示例

**OpenAI text-embedding-3-* / ada-002**（无需指令）

```toml
[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "text-embedding-3-small"
dimensions = 512   # text-embedding-3-* 支持，ada-002 不支持此参数
```

**Qwen3-Embedding**（需要指令，格式：`Instruct: {任务描述}\nQuery: `）

```toml
[models.embedding]
api_url = "http://localhost:8000/v1"   # 本地部署地址
api_key = "EMPTY"
model_name = "Qwen/Qwen3-Embedding"
query_instruction = "Instruct: 为这个搜索查询检索相关文档\nQuery: "
```

代码检索场景可换为：

```toml
query_instruction = "Instruct: 为这个搜索查询检索相关代码片段\nQuery: "
```

**BGE 系列**（如 `BAAI/bge-large-zh-v1.5`）

```toml
[models.embedding]
model_name = "BAAI/bge-large-zh-v1.5"
query_instruction = "为这个句子生成表示以用于检索相关文章："
```

**E5 系列**（如 `intfloat/multilingual-e5-large`，Query 和 Document 都需要前缀）

```toml
[models.embedding]
model_name = "intfloat/multilingual-e5-large"
query_instruction = "query: "
document_instruction = "passage: "
```

> 具体指令内容以各模型官方文档为准。不确定时可先不填，观察检索效果后再调整。

## 重排模型适配

重排模型使用 OpenAI 兼容 `/v1/rerank` 接口，核心输入为：

- `query`：查询文本
- `documents`：待重排文档列表
- `top_n`：返回数量

### query_instruction 说明

部分重排模型要求在 Query 前拼接任务指令，可通过 `models.rerank.query_instruction` 配置。该前缀只作用于**重排阶段**，不影响向量召回阶段的嵌入输入。

### 配置示例

**无需指令前缀**

```toml
[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "text-rerank-001"
query_instruction = ""
```

**需要指令前缀（示例）**

```toml
[models.rerank]
api_url = "http://localhost:8000/v1"
api_key = "EMPTY"
model_name = "my-rerank-model"
query_instruction = "Instruct: 为这个搜索查询重排候选文档\nQuery: "
```

> 指令模板请以具体模型文档为准。

## 手动触发嵌入

如果关闭了自动扫描，可以通过重启机器人触发一次全量扫描，或将 `auto_scan` + `auto_embed` 临时设为 `true` 后热更新配置。

## 注意事项

- 支持常见纯文本格式（如 `.txt/.md/.markdown/.html/.htm/.rst/.csv/.tsv/.json/.yaml/.yml/.xml/.log/.ini/.cfg/.conf`）
- 文本文件应使用 UTF-8 编码
- `chroma/` 目录较大时可手动删除后重新嵌入（会触发全量重建）
- 嵌入模型需兼容 OpenAI `/v1/embeddings` 接口
- 重排模型需兼容 OpenAI `/v1/rerank` 接口
- 建议先确认重排模型是否要求 `query_instruction` 前缀，避免相关性下降
