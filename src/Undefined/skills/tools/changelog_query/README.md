# changelog_query

查询 Undefined 自身维护的 `CHANGELOG.md`。

## action

- `latest`：读取最新版本
- `list`：列出最近多个版本
- `show`：读取指定版本

## 常用参数

- `version`：`show` 时指定版本号
- `limit`：`list` 时限制条数，默认 5，最大 20
- `include_summary`：控制是否返回摘要
- `include_changes`：控制是否返回变更点
- `max_changes`：限制返回的变更点数量

## 返回

返回 JSON 字符串，包含 `ok`、`action`、`items` 或 `entry` 等字段，便于 AI 按需读取和摘要。
