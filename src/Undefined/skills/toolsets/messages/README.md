# messages 工具集

消息相关工具集合，工具名以 `messages.*` 命名。

主要能力：
- 发送群聊/私聊消息
- 发送单文件文本文档（代码/文档/配置）
- 从 URL 下载并发送文件
- 将已有音频附件 UID 显式发送为 QQ/微信语音
- 获取最近消息或转发内容
- 按时间范围查询消息

使用建议：
- 单文件、轻量交付优先使用 `messages.send_text_file`
- 需要把网络文件直接发到群/私聊时使用 `messages.send_url_file`
- 仅在用户明确要求语音消息时使用 `messages.send_voice`；普通 `<attachment uid="..."/>` 保持文件语义
- QQ 本地图片、语音、视频与文件统一由 OneBotClient 根据 `onebot.file_send_mode` 选择 `local`、`url` 或 `stream`（默认）。工具继续提供原始本地路径，保持展示名称、附件 UID 和历史来源不变；已有远程 URL、Base64 和协议端资源标识原样通过。
- 文件准备失败不会计作已发送或触发文件消息段回退。协议端不支持 Stream 时返回包含 `onebot.file_send_mode` 切换方法的说明，工具不得自动换模式或重试。Stream 不支持空文件；URL 模式需要协议端访问已启动的 Runtime。
- Stream／URL 的准备、实际发送和明确失败后的文件消息段回退共用 8 分钟，临时文件保留 16 分钟；URL 副本不会因工具删除源文件而失效。Stream 按块上传，但不保证上游合并及附件登记的整条链路固定内存占用。
- 消息只包含普通附件标签时会直接派发文件，不会先向 OneBot/微信发送空正文；独立文件发送负责写入历史
- OneBot 在文本、附件或语音发送阶段超时时，工具会把结果标记为“未确认但按已投递处理”，禁止 AI 自动重试；私聊不会再尝试群临时会话或其他共享群，只有用户后续明确要求重发时才再次发送。`mark_sent=false` 的后台播报仍保留防重记录，但不会计作本轮用户回复
- 多文件工程、需要执行命令验证或打包交付，优先使用 `code_delivery_agent`
- `messages.send_text_file` 默认单文件大小上限为 `512KB`，可通过 `config.toml` 的 `[messages].send_text_file_max_size_kb` 调整
- `messages.send_url_file` 默认文件大小上限为 `100MB`，可通过 `config.toml` 的 `[messages].send_url_file_max_size_mb` 调整

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）
