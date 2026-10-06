# python_interpreter 工具

在隔离的 Docker 容器内执行 Python 代码，适用于计算、数据处理与逻辑验证。

限制说明：
- 主执行容器**无法访问网络**且只读（`--network none --read-only`）
- 仅挂载本次执行的临时工作目录到 `/tmp`；`send_files` 只能回传该目录内的产物

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `code` | string | 是 | 要执行的 Python 代码 |
| `libraries` | list[string] | 否 | 需要的第三方库；指定后容器会先联网执行 `pip install`，再在无网环境运行代码 |
| `send_files` | list[string] | 否 | 需要回传的容器内 `/tmp/` 产物路径；执行后作为附件返回 |

## 容器内使用宿主 Docker

源码或 `host` 模式下，Bot 与 Docker daemon 使用同一宿主文件系统，工具默认在系统临时目录中创建工作目录。

Bot 本身在容器中且挂载宿主 Docker socket 时，Docker 的 bind mount 来源由宿主 daemon 解析，需要显式映射共享目录的两端路径。`uv run deploy up` 的 `container` 模式自动复用已有 `data/` 挂载，并设置：

| Bot 环境变量 | 一键部署中的值 |
|---|---|
| `UNDEFINED_PYTHON_INTERPRETER_LOCAL_DIR` | `/data/Undefined/data/cache/python_interpreter`，Bot 可读写的共享目录 |
| `UNDEFINED_PYTHON_INTERPRETER_HOST_DIR` | 当前仓库的 `deploy/data/cache/python_interpreter` 绝对路径，宿主 Docker 可见的同一目录 |

手工部署时，同时设置这两个变量为对应的绝对路径，并保证指向同一份共享目录。工具在 Bot 侧创建独立工作目录、写入脚本，向 Docker 传入对应宿主路径，再从 Bot 侧读取输出并清理。不会挂载整个宿主 `/tmp`。更换仓库位置后应重新生成部署配置，避免保留旧的宿主绝对路径。

执行目录在完成后清理；需要回传文件时会保留 30 秒，让附件发送完成。创建目录期间收到取消时，会先等待后台创建线程结束，再清理本次目录并传播取消，避免遗留临时工作目录。

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
