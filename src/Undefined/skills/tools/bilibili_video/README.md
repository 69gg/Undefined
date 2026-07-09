# bilibili_video 工具

处理 Bilibili 视频。默认发送到群聊或私聊；也支持只注册为附件 UID 供文件分析使用，或只获取视频信息。支持 BV 号、AV 号或 B 站视频链接。

依赖：
- 系统需安装 `ffmpeg`（用于合并 DASH 音视频流）
- Bilibili 自动提取的弹幕 protobuf 解码由项目内置逻辑完成，无需安装 `protoc`

常用参数：
- `video_id`：视频标识（BV 号、AV 号或完整 URL）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID
- `output_mode`：可选，`send`（默认，发送合并转发）、`uid`（只返回 `<attachment uid="file_xxx"/>`，不发送消息）或 `info`（只返回视频信息，不下载不发送）

`send` 模式流程：
1. 解析 `video_id` 为 BV 号
2. 调用项目内 `Undefined.bilibili` 模块获取视频信息
3. 下载 DASH 音视频流并通过 ffmpeg 合并
4. 通过 `[CQ:video]` 发送到目标会话
5. 超限时降级为封面+标题+简介信息卡片

`uid` 模式流程：
1. 下载并按大小限制处理视频
2. 注册为当前会话附件 UID
3. 返回视频概要和 `<attachment uid="file_xxx"/>`，供 `file_analysis_agent` 继续分析

`info` 模式流程：
1. 解析 `video_id` 为 BV 号
2. 调用项目内 `Undefined.bilibili` 模块获取视频信息
3. 返回标题、UP 主、时长、互动统计、简介、封面 URL 和视频链接
4. 不下载视频、不发送消息、不注册附件

配置依赖：
- `config.toml` 中的 `[bilibili]` 段控制清晰度、时长限制、文件大小限制等

自动提取行为：
- 自动处理管线命中 B 站链接、BV 号或 AV 号后，会发送一次外层合并转发，包含视频信息、视频文件或视频状态、弹幕列表三个节点。
- 弹幕通过 Bilibili protobuf 接口分段拉取；弹幕列表会按每 100 条弹幕拆成一个内层合并转发。
- 每条弹幕会作为内层合并转发中的独立节点发送，便于逐条查看和引用。

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
