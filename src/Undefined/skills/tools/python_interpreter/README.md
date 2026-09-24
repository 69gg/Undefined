# python_interpreter 工具

在隔离的 Docker 容器内执行 Python 代码，适用于计算、数据处理与逻辑验证。

限制说明：
- 主执行容器**无法访问网络**且只读（`--network none --read-only`）
- 无法访问宿主机文件系统（`send_files` 除外，见下）

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 要执行的 Python 代码 |
| `libraries` | list[string] | 否 | 需要的第三方库；指定后容器会先联网执行 `pip install`，再在无网环境运行代码 |
| `send_files` | list[string] | 否 | 需要回传的容器内 `/tmp/` 产物路径；执行后作为附件返回 |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
