# /version（/v）

查看当前版本号与最新版本变更标题。

- 用法：`/version`
- 数据来源：`pyproject.toml` 的构建版本 + `CHANGELOG.md` 最新条目标题
- 别名：`v`

目录结构：
- `config.json`：命令定义（权限 / 限流 / 别名）
- `handler.py`：执行逻辑
