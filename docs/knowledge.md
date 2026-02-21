# 本地知识库

## 功能概述

将本地纯文本文件向量化后存入 ChromaDB，AI 可通过三个工具查询：

| 工具 | 说明 |
|------|------|
| `knowledge_list` | 列出所有可用知识库 |
| `knowledge_text_search` | 关键词搜索原始文本 |
| `knowledge_semantic_search` | 语义相似度搜索 |

## 目录结构

```
knowledge/                        # 项目根目录，仅存数据
└── {知识库名}/
    ├── texts/                    # 原始文本（*.txt，扁平结构）
    ├── chroma/                   # ChromaDB 向量库（自动生成）
    └── .manifest.json            # 文件 hash 记录（自动生成）
```

`knowledge/` 下不放代码，只有数据文件。`chroma/` 和 `.manifest.json` 已加入 `.gitignore`。

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

[knowledge]
enabled = true
base_dir = "knowledge"            # 知识库根目录
auto_scan = true                  # 定期扫描文本变更
auto_embed = true                 # 发现变更自动嵌入
scan_interval = 60                # 扫描间隔（秒）
embed_batch_size = 64             # 每批嵌入块数
chunk_size = 10                   # 每个向量块包含的行数（滑动窗口大小）
chunk_overlap = 2                 # 相邻块重叠的行数
default_top_k = 5                 # 语义搜索默认返回数
```

**2. 放入文本文件**

```
knowledge/
└── my_docs/
    └── texts/
        ├── faq.txt
        └── manual.txt
```

**3. 启动机器人**

启动后自动扫描并嵌入，日志中会出现：

```
[知识库] 初始化完成: base_dir=knowledge
[知识库] kb=my_docs file=faq.txt lines=42
```

## 工具用法

### knowledge_list

无参数，返回所有知识库名称列表。

```json
["my_docs", "product_manual"]
```

### knowledge_text_search

在原始文本中按关键词搜索（大小写不敏感）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | string | ✓ | 知识库名称 |
| `keyword` | string | ✓ | 搜索关键词 |
| `max_lines` | integer | | 最多返回行数，默认 20 |
| `max_chars` | integer | | 最多返回字符数，默认 2000 |

返回示例：

```json
[
  {"source": "faq.txt", "line": 12, "content": "如何重置密码？"},
  {"source": "manual.txt", "line": 5, "content": "密码长度不少于8位"}
]
```

### knowledge_semantic_search

通过嵌入向量计算语义相似度，返回最相关的行。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | string | ✓ | 知识库名称 |
| `query` | string | ✓ | 查询文本 |
| `top_k` | integer | | 返回数量，默认取配置值 |

返回示例：

```json
[
  {"content": "重置密码需要验证手机号", "source": "faq.txt", "relevance": 0.91},
  {"content": "忘记密码可联系客服", "source": "faq.txt", "relevance": 0.87}
]
```

## 工作原理

### 文本切分

每个 `.txt` 文件先按行切分并忽略空行，再用**滑动窗口**合并为向量块：

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

嵌入请求通过内置队列串行发送，按 `queue_interval_seconds` 控制发车间隔，避免超出 API 速率限制。多行文本按 `embed_batch_size` 分批，每批一次 API 调用。

```
texts → split_lines → [batch 1, batch 2, ...] → Queue → API (间隔发车)
```

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

## 手动触发嵌入

如果关闭了自动扫描，可以通过重启机器人触发一次全量扫描，或将 `auto_scan` + `auto_embed` 临时设为 `true` 后热更新配置。

## 注意事项

- 目前仅支持 `.txt` 纯文本文件
- 文本文件应使用 UTF-8 编码
- `chroma/` 目录较大时可手动删除后重新嵌入（会触发全量重建）
- 嵌入模型需兼容 OpenAI `/v1/embeddings` 接口
