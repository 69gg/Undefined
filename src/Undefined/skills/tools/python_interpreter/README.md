# python_interpreter 工具

在隔离的 Docker 容器内执行 Python 代码，适用于计算、数据处理与逻辑验证。

限制说明：
- 无法访问网络
- 无法访问宿主机文件系统

常用参数：
- `code`：要执行的 Python 代码

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
