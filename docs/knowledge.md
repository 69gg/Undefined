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

[knowledge]
enabled = true
base_dir = "knowledge"            # 知识库根目录
auto_scan = true                  # 定期扫描文本变更
auto_embed = true                 # 发现变更自动嵌入
scan_interval = 60                # 扫描间隔（秒）
embed_batch_size = 64             # 每批嵌入行数
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

每个 `.txt` 文件按行切分，忽略空行。每一行作为一个独立的向量单元存入 ChromaDB。

### 增量嵌入

`.manifest.json` 记录每个文件的 SHA256 hash。扫描时只对新增或内容变更的文件重新嵌入，未变更的文件跳过。

### 站台/发车队列

嵌入请求通过内置队列串行发送，按 `queue_interval_seconds` 控制发车间隔，避免超出 API 速率限制。多行文本按 `embed_batch_size` 分批，每批一次 API 调用。

```
texts → split_lines → [batch 1, batch 2, ...] → Queue → API (间隔发车)
```

### 向量存储

使用 ChromaDB 的 cosine 距离度量。每行内容的 SHA256 前 16 位作为 ID，重复内容自动去重（upsert）。

## 手动触发嵌入

如果关闭了自动扫描，可以通过重启机器人触发一次全量扫描，或将 `auto_scan` + `auto_embed` 临时设为 `true` 后热更新配置。

## 注意事项

- 目前仅支持 `.txt` 纯文本文件
- 文本文件应使用 UTF-8 编码
- `chroma/` 目录较大时可手动删除后重新嵌入（会触发全量重建）
- 嵌入模型需兼容 OpenAI `/v1/embeddings` 接口
