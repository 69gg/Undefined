# bilibili_video 工具

下载并发送 Bilibili 视频到群聊或私聊。支持 BV 号、AV 号或 B 站视频链接。

依赖：
- 系统需安装 `ffmpeg`（用于合并 DASH 音视频流）

常用参数：
- `video_id`：视频标识（BV 号、AV 号或完整 URL）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID

运行流程：
1. 解析 `video_id` 为 BV 号
2. 调用 B 站 API 获取视频信息和 DASH 流地址
3. 下载音视频流并用 ffmpeg 合并为 MP4
4. 通过 `[CQ:video]` 发送到目标会话
5. 超限时降级为封面+标题+简介信息卡片

配置依赖：
- `config.toml` 中的 `[bilibili]` 段控制清晰度、时长限制、文件大小限制等

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
