# knowledge_text_search 工具

在知识库文本中关键词搜索（结构化紧凑输出），支持大小写与文件路径过滤。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `knowledge_base` | `string` | 是 | 知识库名称 |
| `keyword` | `string` | 是 | 搜索关键词 |
| `max_lines` | `integer` | 否 | 最多返回行数，默认 20 |
| `max_chars` | `integer` | 否 | 总字符上限（搜索阶段），默认 2000 |
| `max_chars_per_item` | `integer` | 否 | 每条结果最大字符数（输出阶段裁剪），默认 180 |
| `case_sensitive` | `boolean` | 否 | 是否大小写敏感，默认 false |
| `source_keyword` | `string` | 否 | 按 source 路径关键词过滤（例如 docs/faq） |
| `include_source` | `boolean` | 否 | 是否输出 source 字段，默认 true |
| `include_line` | `boolean` | 否 | 是否输出 line 字段，默认 true |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
