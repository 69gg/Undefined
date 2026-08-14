# 斜杠命令查询工具集

主 AI 可用这些工具查询当前发送者能执行的斜杠命令。匹配为纯文本子串，不接 RAG。

- `commands.search`：按名称/别名/说明/用法/文档检索可见命令
- `commands.get`：取单条命令的权限、限流、用法和 README

该分类没有 `callable.json`，默认仅主 AI 可见。
