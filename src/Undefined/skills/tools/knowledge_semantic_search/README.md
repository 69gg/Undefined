# knowledge_semantic_search 工具

语义检索（结构化紧凑输出），支持重排与结果后过滤。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | `string` | 是 | 知识库名称 |
| `query` | `string` | 是 | 查询文本 |
| `top_k` | `integer` | 否 | 语义召回数量，默认取知识库配置值 |
| `enable_rerank` | `boolean` | 否 | 是否启用重排。不传时使用知识库默认配置 |
| `rerank_top_k` | `integer` | 否 | 重排后返回数量，需小于语义召回数量 |
| `min_relevance` | `number` | 否 | 最小相关度阈值（0-1），默认 0 |
| `source_keyword` | `string` | 否 | 按 source 路径关键词过滤（不区分大小写） |
| `max_chars_per_item` | `integer` | 否 | 每条结果最大字符数，默认 220 |
| `include_rerank_score` | `boolean` | 否 | 是否输出 rerank_score，默认 true |
| `deduplicate` | `boolean` | 否 | 按 source+text 去重，默认 true |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
