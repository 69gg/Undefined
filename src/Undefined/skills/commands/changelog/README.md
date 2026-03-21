# /changelog 命令说明

用于查看仓库内 `CHANGELOG.md` 中维护的版本历史。

## 用法

- `/changelog`
- `/changelog list`
- `/changelog list 12`
- `/changelog show v3.2.6`
- `/changelog show 3.2.6`
- `/changelog latest`

## 说明

- `/changelog` 默认列最近 8 个版本。
- `list [数量]` 按新到旧列版本与标题，最大 20。
- `show <版本号>` 展示单个版本的标题、摘要和变更点。
- `latest` 展示 `CHANGELOG.md` 中第一条版本详情。
- 版本数据直接来自仓库维护的 `CHANGELOG.md`，不会运行时扫描 git tag。
