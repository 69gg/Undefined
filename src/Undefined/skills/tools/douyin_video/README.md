# douyin_video 工具

下载抖音视频。默认发送到群聊或私聊；也支持只注册为附件 UID 供文件分析使用。支持 `v.douyin.com` 短链、`douyin.com/video/<id>` 长链或裸 `aweme_id`。

常用参数：
- `video_id`：抖音视频标识
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID
- `output_mode`：可选，`send`（默认，发送合并转发）或 `uid`（只返回 `<attachment uid="file_xxx"/>`，不发送消息）

`send` 模式会发送一条两节点合并转发：视频信息、视频文件或视频状态。`uid` 模式会下载视频并注册为当前会话附件 UID，供 `file_analysis_agent` 继续分析。

配置依赖：
- `config.toml` 中的 `[douyin]` 段控制代理、自动提取、时长限制、文件大小限制和清晰度探测顺序。
