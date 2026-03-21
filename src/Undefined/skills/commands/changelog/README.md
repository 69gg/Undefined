# /changelog 命令说明

用于查看仓库内 `CHANGELOG.md` 中维护的版本历史。

## 用法

- `/changelog`
- `/cl`
- `/changelog 12`
- `/changelog list`
- `/changelog list 12`
- `/changelog v3.2.6`
- `/changelog 3.2.6`
- `/changelog show v3.2.6`
- `/changelog show 3.2.6`
- `/changelog latest`

## 说明

- `/changelog` 默认列最近 8 个版本。
- `/changelog <数量>` 会直接列出最近 N 个版本。
- `/changelog <版本号>` 会直接展示对应版本详情。
- `list [数量]` 按新到旧列版本与标题。
- 群聊里当请求数量大于 20 时，会改用合并转发发送完整列表，避免普通消息里看不全。
- 私聊里不会走合并转发，而是直接发普通文本消息。
- `show <版本号>` 展示单个版本的标题、摘要和变更点。
