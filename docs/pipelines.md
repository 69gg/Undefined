# 自动处理管线开发指南

自动处理管线位于 `src/Undefined/skills/pipelines/`，用于在普通消息进入 AI 自动回复前执行自动提取，例如 Bilibili 视频、arXiv 论文和 GitHub 仓库卡片。斜杠命令优先级高于自动处理管线，命中命令后不会继续触发自动提取或 AI 回复。

`MessageHandler` 启动时会通过异步初始化在线程中加载管线配置和 handler 模块，避免目录扫描、`config.json` 读取和模块导入阻塞事件循环；注册 OneBot 消息回调前会等待首次加载完成，后续热重载也在线程中执行。

## 运行顺序

1. `MessageHandler` 先并行执行消息预处理：附件收集、历史文本解析、昵称或群信息读取等。图片、文件等媒体会登记为附件 UID，并在 AI 可见正文中统一写作 `<attachment uid="..."/>`。
2. 用户消息先写入历史。
3. 若消息命中斜杠命令，立即分发命令并结束本轮后续流程；命令输入和命令输出会写入历史，供后续 AI 轮次读取。
4. 未命中命令时，`PipelineRegistry` 并行调用所有已注册管线的 `detect(context)`。
5. 对所有命中的管线，并行调用对应的 `process(detection, context)`。
6. 管线发送出的信息、图片、文件或视频摘要通过统一发送器写入历史；本地图片、文件和视频会自动登记为当前会话可见的统一附件 UID，历史正文同样使用 `<attachment uid="..."/>` 作为可复用引用。
7. 自动处理完成后，当前消息和管线输出一起进入 AI 自动回复/Agent 循环。

命中自动处理管线的消息会继续进入 AI 自动回复，让 AI 基于用户消息和刚写入的自动处理结果判断后续行为。

## 内置 Bilibili 管线

Bilibili 自动提取管线命中 B 站链接、BV 号或 AV 号后，会发送一次外层合并转发，外层固定包含三个节点：视频信息、视频文件或视频状态、弹幕列表。

弹幕使用 Bilibili protobuf 接口分段拉取，解码逻辑随项目代码提供；部署和开发时无需安装 `protoc`，也不需要手动生成 protobuf 文件。弹幕列表节点会继续拆成内层合并转发，每 100 条弹幕一个内层合并转发；每条弹幕作为内层合并转发中的独立节点发送。

## 目录结构

```text
src/Undefined/skills/pipelines/
├── __init__.py
├── registry.py
├── models.py
├── context.py
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

- `name`: 管线唯一名称，必须与 `PipelineDetection.name` 一致。
- `description`: 日志和维护说明。
- `order`: 注册排序字段，仅用于稳定展示和结果收集顺序；处理不依赖优先级。
- `enabled`: 设为 `false` 时该管线不会加载。

## `handler.py`

```python
from __future__ import annotations

from Undefined.skills.pipelines.models import PipelineContext, PipelineDetection


async def detect(context: PipelineContext) -> PipelineDetection | None:
    text = str(context["text"])
    if "example" not in text:
        return None
    return PipelineDetection(name="example", items=("example",))


async def process(
    detection: PipelineDetection,
    context: PipelineContext,
) -> None:
    handler = context["handle_bilibili_extract"]
    await handler(
        int(context["target_id"]),
        ["example"],
        str(context["target_type"]),
    )
```

handler.py 需要导出 `detect` 和 `process` 两个顶层异步函数。

## Context 参数

`detect(context)` 和 `process(detection, context)` 共享的 `context` 字典由 `build_pipeline_context()` 构建，包含以下常用字段：

| key | 类型 | 说明 |
|-----|------|------|
| `config` | object | 运行时配置对象（含 `xxx_auto_extract_enabled`、`is_xxx_auto_extract_allowed_group/private` 等方法） |
| `sender` | object | 消息发送器 |
| `onebot` | object | OneBot 客户端 |
| `target_id` | int | 群号或私聊 QQ 号 |
| `target_type` | str | `"group"` 或 `"private"` |
| `text` | str | 提取的纯文本内容 |
| `message_content` | list[dict] | 原始消息段列表 |
| `extract_xxx_ids` | callable | 提取器函数 |
| `handle_xxx_extract` | callable | 处理器函数 |

## 注册与热重载

`PipelineRegistry` 在初始化时扫描 `pipelines/` 下每个子目录，按 `order` 排序注册。

热重载每 2 秒（可配置）检查 `config.json` 和 `handler.py` 的 mtime + size 快照，检测到变更后等待 500ms 防抖再重载。新增或删除目录也会在重载时生效。

`PipelineRegistry` 监视 `config.json` 和 `handler.py` 的变更。如果只改 `README.md` 不会触发重载。
