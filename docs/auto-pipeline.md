# 自动处理管线开发指南

自动处理管线位于 `src/Undefined/skills/auto_pipeline/`，用于在普通消息进入斜杠命令和 AI 自动回复前执行自动提取，例如 Bilibili 视频、arXiv 论文和 GitHub 仓库卡片。

## 运行顺序

1. `MessageHandler` 先并行执行消息预处理：附件收集、历史文本解析、昵称或群信息读取等。
2. 用户消息先写入历史。
3. `AutoPipelineRegistry` 并行调用所有已注册管线的 `detect(context)`。
4. 对所有命中的管线，并行调用对应的 `process(detection, context)`。
5. 管线发送出的信息、图片、文件或视频摘要通过统一发送器写入历史。
6. 自动处理完成后，当前消息和管线输出一起进入 AI 自动回复/Agent 循环。

命中自动处理管线的消息不会再进入斜杠命令分发；它会继续进入 AI 自动回复，让 AI 基于用户消息和刚写入的自动处理结果判断后续行为。

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

`detect` 应只做轻量检测和 ID 提取；`process` 执行下载、渲染、发送等重操作。发送消息应优先走 `MessageSender`，不要绕过历史写入。

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