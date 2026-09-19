# knowledge_list 工具

列出知识库（紧凑结构化输出），支持按名称过滤、控制简介与返回数量。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `only_ready` | `boolean` | 否 | 是否仅返回已配置 intro.md 的知识库，默认 true |
| `include_intro` | `boolean` | 否 | 是否返回简介内容，默认 true |
| `include_has_intro` | `boolean` | 否 | 是否返回 has_intro 字段，默认 false |
| `intro_max_chars` | `integer` | 否 | 每个知识库简介最大字符数，默认 120 |
| `max_items` | `integer` | 否 | 最多返回多少个知识库，默认 50 |
| `name_keyword` | `string` | 否 | 按知识库名称关键词过滤（不区分大小写） |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
