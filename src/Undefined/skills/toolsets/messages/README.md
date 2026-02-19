# messages 工具集

消息相关工具集合，工具名以 `messages.*` 命名。

主要能力：
- 发送群聊/私聊消息
- 发送单文件文本文档（代码/文档/配置）
- 从 URL 下载并发送文件
- 获取最近消息或转发内容
- 按时间范围查询消息

使用建议：
- 单文件、轻量交付优先使用 `messages.send_text_file`
- 需要把网络文件直接发到群/私聊时使用 `messages.send_url_file`
- 多文件工程、需要执行命令验证或打包交付，优先使用 `code_delivery_agent`
- `messages.send_text_file` 默认单文件大小上限为 `512KB`，可通过 `config.toml` 的 `[messages].send_text_file_max_size_kb` 调整
- `messages.send_url_file` 默认文件大小上限为 `100MB`，可通过 `config.toml` 的 `[messages].send_url_file_max_size_mb` 调整

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）
