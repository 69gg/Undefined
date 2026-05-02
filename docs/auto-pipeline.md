# 自动处理管线开发指南

自动处理管线位于 `src/Undefined/skills/auto_pipeline/`，用于在普通消息进入 AI 自动回复前执行自动提取，例如 Bilibili 视频、arXiv 论文和 GitHub 仓库卡片。斜杠命令优先级高于自动处理管线，命中命令后不会继续触发自动提取或 AI 回复。

`MessageHandler` 启动时会通过异步初始化在线程中加载管线配置和 handler 模块，避免目录扫描、`config.json` 读取和模块导入阻塞事件循环；注册 OneBot 消息回调前会等待首次加载完成，后续热重载也在线程中执行。

## 运行顺序

1. `MessageHandler` 先并行执行消息预处理：附件收集、历史文本解析、昵称或群信息读取等。
2. 用户消息先写入历史。
3. 若消息命中斜杠命令，立即分发命令并结束本轮后续流程；命令输入和命令输出会写入历史，供后续 AI 轮次读取。
4. 未命中命令时，`AutoPipelineRegistry` 并行调用所有已注册管线的 `detect(context)`。
5. 对所有命中的管线，并行调用对应的 `process(detection, context)`。
6. 管线发送出的信息、图片、文件或视频摘要通过统一发送器写入历史；本地图片、文件和视频会自动登记为当前会话可见的统一附件 UID。
7. 自动处理完成后，当前消息和管线输出一起进入 AI 自动回复/Agent 循环。

命中自动处理管线的消息会继续进入 AI 自动回复，让 AI 基于用户消息和刚写入的自动处理结果判断后续行为。

## 目录结构

```text
src/Undefined/skills/auto_pipeline/
├── registry.py
├── models.py
└── pipelines/
    ├── bilibili/
    │   ├── config.json
    │   └── handler.py
    ├── arxiv/
    │   ├── config.json
    │   └── handler.py
    └── github/
        ├── config.json
        └── handler.py
```

## `config.json`

```json
{
    "name": "example",
    "description": "检测并处理某类自动提取消息。",
    "order": 100,
    "enabled": true
}
```

- `name`: 管线唯一名称，必须与 `AutoPipelineDetection.name` 一致。
- `description`: 日志和维护说明。
- `order`: 注册排序字段，仅用于稳定展示和结果收集顺序；处理不依赖优先级。
- `enabled`: 设为 `false` 时该管线不会加载。

## `handler.py`

```python
from __future__ import annotations

from Undefined.skills.auto_pipeline.models import AutoPipelineContext, AutoPipelineDetection


async def detect(context: AutoPipelineContext) -> AutoPipelineDetection | None:
    text = str(context["text"])
    if "example" not in text:
        return None
    return AutoPipelineDetection(name="example", items=("example",))


async def process(
    detection: AutoPipelineDetection,
    context: AutoPipelineContext,
) -> None:
    sender = context["sender"]
    target_id = int(context["target_id"])
    target_type = str(context["target_type"])
    message = f"自动处理结果: {', '.join(detection.items)}"
    if target_type == "group":
        await sender.send_group_message(target_id, message)
    else:
        await sender.send_private_message(target_id, message)
```

`detect` 应只做轻量检测和 ID 提取；`process` 执行下载、渲染、发送等重操作。发送消息应优先走 `MessageSender`，不要绕过历史写入。`MessageSender` 会自动将本地 CQ 图片、视频、语音以及 `send_group_file` / `send_private_file` 上传的文件登记为会话附件，让历史中带上 `pic_*` / `file_*` UID，便于后续 AI 回复引用；管线通常不需要单独处理附件登记。

## 附件 UID 绑定语义

- 外部接收的远程图片或文件默认会先下载并写入附件缓存，UID 绑定的是缓存中的文件内容；超过 `[attachments].remote_download_max_size_mb` 时会降级为 URL 引用，UID 绑定原始 URL 而不下载文件内容。原始 URL、OneBot `file` 标识或 WebUI 文件 ID 会保存在 `source_ref` / `segment_data` 中用于追溯。
- 外部接收的本地路径、`file://` 路径或 WebUI 已上传文件会被复制到附件缓存，UID 同样绑定缓存副本，而不是直接绑定原路径。
- 内部生成或发送的本地媒体、视频、语音和上传文件由 `MessageSender` 在发送成功后读取并登记，UID 绑定发送当时复制进缓存的内容；原始本地路径或 CQ `file` 字段作为来源信息保留。

## Context 字段

常用字段：

- `config`: 当前运行配置。
- `sender`: 统一消息发送器。
- `onebot`: OneBot 客户端。
- `target_id`: 群号或私聊用户 QQ。
- `target_type`: `group` 或 `private`。
- `text`: 当前消息纯文本。
- `message_content`: 当前消息原始结构化段。
- `extract_bilibili_ids`、`extract_arxiv_ids`、`extract_github_repo_ids`: 现有解析 helper。
- `handle_bilibili_extract`、`handle_arxiv_extract`、`handle_github_extract`: 现有发送处理 helper。

新增管线可以复用已有解析器和发送器，避免重复网络、解析和历史写入逻辑。

## 热重载

`AutoPipelineRegistry` 监视 `config.json` 和 `handler.py`，并跟随 `[skills]` 配置：

```toml
[skills]
hot_reload = true
hot_reload_interval = 2.0
hot_reload_debounce = 0.5
```

修改管线文件后，运行中的机器人会在去抖后重新加载管线。禁用 `[skills].hot_reload` 会同时停止自动处理管线、工具和 Agent 的热重载 watcher。