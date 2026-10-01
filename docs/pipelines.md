# 自动处理管线开发指南

自动处理管线位于 `src/Undefined/skills/pipelines/`，用于在普通消息进入 AI 自动回复前执行自动提取，例如 Bilibili 视频、Bilibili 图文（opus）、抖音视频、arXiv 论文、GitHub 仓库卡片和禁漫（JM）本子。斜杠命令优先级高于自动处理管线，命中命令后不会继续触发自动提取或 AI 回复。

`MessageHandler` 启动时会通过异步初始化在线程中加载管线配置和 handler 模块，避免目录扫描、`config.json` 读取和模块导入阻塞事件循环；注册 OneBot 消息回调前会等待首次加载完成，后续热重载也在线程中执行。

## 运行顺序

1. `MessageHandler` 先并行执行消息预处理：附件收集、历史文本解析、昵称或群信息读取等。图片、文件等媒体会登记为附件 UID，并在 AI 可见正文中统一写作 `<attachment uid="..."/>`；合并转发会登记为 `<forward uid="forward_xxx"/>`，同时递归保存当前可访问的转发树快照，不在实时 AI 输入中自动展开。
2. 用户消息先写入历史。历史记录仍会递归展开合并转发文本，保持历史检索和旧行为兼容；同一轮 prompt 会剔除当前消息的历史副本，实时 AI 输入只保留 forward UID，AI 需要查看第一层或内层内容时调用 `messages.get_forward_msg` 按层读取。
3. 若消息命中斜杠命令，立即分发命令并结束本轮后续流程；命令输入和命令输出会写入历史，供后续 AI 轮次读取。
4. 未命中命令时，`PipelineRegistry` 并行调用所有已注册管线的 `detect(context)`。
5. 对所有命中的管线，并行调用对应的 `process(detection, context)`。
6. 管线发送出的信息、图片、文件或视频摘要通过统一发送器写入历史；本地图片、文件和视频会自动登记为当前会话可见的统一附件 UID，历史正文同样使用 `<attachment uid="..."/>` 作为可复用引用。需要“只获取 UID 不发送”或“只获取元信息”的 arXiv/Bilibili/Douyin 分析场景由 `file_analysis_agent` 调用共享主工具处理，不改变自动管线的发送行为。
7. 自动处理完成后，当前消息和管线输出一起进入 AI 自动回复/Agent 循环。

命中自动处理管线的消息会继续进入 AI 自动回复，让 AI 基于用户消息和刚写入的自动处理结果判断后续行为。

合并转发里的图片仍会在后台递归扫描并进入表情包入库队列；该扫描不把转发文本或图片列表追加到实时 AI 上下文，避免大型转发树撑爆上下文。

## 内置 Bilibili 管线

Bilibili 自动提取管线命中 B 站链接、BV 号或 AV 号后，会发送一次外层合并转发，外层固定包含三个节点：视频信息、视频文件或视频状态、弹幕列表。

弹幕使用 Bilibili protobuf 接口分段拉取，解码逻辑随项目代码提供；部署和开发时无需安装 `protoc`，也不需要手动生成 protobuf 文件。弹幕列表节点会继续拆成内层合并转发，每 100 条弹幕一个内层合并转发；每条弹幕作为内层合并转发中的独立节点发送。

## 内置 Douyin 管线

Douyin 自动提取管线命中 `v.douyin.com/...`、`douyin.com/video/<id>` 或裸 aweme_id 后，会发送一次两节点合并转发：视频信息、视频文件或视频状态。裸数字只匹配不落在任何链接内的 16–25 位数字：链接里的 ID（如 `bilibili.com/opus/933099353259638816`）不会被当成 aweme_id，否则同一张图文链接会同时触发图文与抖音两条管线。排除范围包含可选端口、路径、查询参数和片段，即使 `?` 或 `#` 紧跟域名、没有 `/`，其中的数字也不会触发抖音提取。

下载链路读取抖音 SSR share 页中的 `window._ROUTER_DATA`，从 `video.play_addr` 提取 token，再按 `[douyin].prefer_ratios` 探测 `aweme/v1/play/`。探测使用 2 字节 Range GET，并优先按 `Content-Range` 中的总长度对重复文件去重，缺失时回退 `Content-Length`。

## 内置 Bilibili 图文（opus）管线

Bilibili 图文管线命中 `bilibili.com/opus/<id>`、`t.bilibili.com/<id>`、`b23.tv` 短链或 QQ 小程序分享卡片后，发送一次外层合并转发，节点顺序固定：

1. `图文信息`：封面 + 标题 / UP主 / 时间 / 阅读点赞评论转发 / 原文链接；
2. `正文 …`：正文文本与图片按原始顺序混排，按单节点 1200 字（`format.NODE_TEXT_BUDGET`）与 9 张图切分（`正文 1/12` 这类节点名），不截断、不丢内容；正文超过一个节点时整体收进顶层 `正文` 节点的嵌套内容——NapCat packet 模式会把**顶层节点**的全部文本写进转发卡片的 `news` 预览，顶层塞满整篇正文会让卡片膨胀到几十 KB 并被 QQ 拒收（`发送转发消息（res_id：… 失败`，retcode=1200），下沉一层后卡片体积与正文长度解耦；
3. 嵌套节点：正文里的图文卡片与视频卡片各自成为独立嵌套合并转发（`嵌套图文: …` / `嵌套视频: …`），其它卡片类型渲染为单个 `链接卡片` 节点。

嵌套展开受 `[bilibili].opus_nested_depth`（默认 5 层）与 `opus_nested_max_cards`（默认 8 张）约束，超出边界时卡片降级为一行 `标题 — 链接` 文本节点。嵌套视频会真实下载视频文件并复用视频侧的清晰度/时长/体积限制，超限或失败时只发信息节点。

数据来源与解析：

- 优先 `https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail`（`modules` 为列表，按 `module_type` 分组）；
- 失败时回退 `https://api.bilibili.com/x/polymer/web-dynamic/v1/detail`（`modules` 为字典，正文在 `module_dynamic.desc.text`，图片在 `module_dynamic.major.draw`）；
- `OpusInfo` 的 `blocks` 由 `module_content.paragraphs[]` 按 `para_type` 转换而来：文本 1、图片 2、分割线 3、块引用 4、列表 5、链接卡片 6、代码 7。

管线只在 `auto_extract_enabled` 与 `opus_enabled` 同时为真、且会话命中白名单时生效；与视频管线相互独立，同一条消息同时包含 BV 号与图文链接时两条管线各自发送。

## 内置 JM（禁漫）管线

JM 管线命中 `JM` 前缀加 5–8 位车号（`JM1114751`、`jm 1114751`、`jm:1114751`）或主机名含 `18comic` / `jmcomic` 的链接（`/album/<id>`、`/photo/<id>`、`?id=<id>`）后，发送一次外层合并转发，节点顺序固定：

1. `本子信息`：车号与标题、作者、章节数、标签、观看/点赞、页数、PDF 大小、简介预览，末行是可直接复制的 `JM<车号>`（不带站点链接）；
2. `解密密码`：每次随机生成的 8 位 PDF 打开密码；
3. `PDF`：本地合成好的加密 PDF（群聊下会作为真正的群文件上传）。

PDF 随转发一起上传，节点里的文件可以直接下载（已用 14MB 的 PDF 实测）；群聊下 NapCat 会把它作为群文件上传（`isGroupFile`、`busid=102`，元素里带 `fileId` / `fileMd5` / `fileSha1`），所以同一个 PDF 也会出现在群文件列表里。文件只发一次，不额外发独立文件消息；只有转发本身发送失败时才退化为「信息 + 密码 + 独立文件消息」。

多章节本子按章节顺序全部下载（`[jm].max_chapters` 可限制），再合成为一个 AES-256 加密 PDF。裸数字不触发，避免群号、时间戳等误报；`xxjm1234567` 这类前缀也不触发。

失败语义：

- 转发被拒时退化为两条普通消息（信息、密码）+ 独立文件消息（这种兜底情况下文件没有别的入口）。密码始终不会写进历史摘要。
- 下载量或 PDF 体积超过 `[jm].max_file_size`（原始图片累计预判 + 组装时按编码后字节复核）、以及没有下到任何页面时，只发信息与状态两个节点，不发密码与文件。

PDF 合成没有走 `jmcpy.imaging.write_pdf`，而是自己用 PyMuPDF 逐页写入：jmcpy 的下载 API 一章只能产出一个 PDF，而这里要把多个章节合进同一个文件；同时 PATH 输出会先把解扰后的图重新编码一次、合成时再编码第二次，这里改为 `decode=False` 取服务端原始字节（无损落盘）、自己解扰、每页只编码一次 JPEG（`[jm].image_quality`，色度 4:4:4）后直接作为 PDF 图像数据，并按 `[jm].pdf_dpi` 统一页尺寸、做 AES-256 加密。页像素始终不做缩放，画质上限由站点源图自身分辨率决定。（jmcpy ≤0.1.1 的 `write_pdf` 另有「追加页退回 72 DPI、同文档页尺寸不一致」的问题，已在 0.1.2 修复；页内色度采样从 0.1.3 起默认也是 4:4:4。本管线依赖 `jmcpy>=0.1.3`。）

AI 侧另有 `jm_book` 工具（`src/Undefined/skills/tools/jm_book/`），与 `arxiv_paper` 同构：`send` 等价自动提取，`uid` 只注册未加密 PDF 附件 UID（共享给 `file_analysis_agent`），`info` 只取详情。

实现说明：图片解码与 PDF 合成是同步 CPU 工作，下载整体在 `asyncio.to_thread` 中通过 jmcpy 的同步客户端执行，不阻塞事件循环；单次任务不可取消，由 `[jm].request_timeout` / `image_timeout` 与 jmcpy 的多端点重试兜底。PDF 在内存中合成后写盘，因此 `[jm].max_file_size` 只是近似内存上限（预判按源图字节、复核按编码后字节，JPEG 重编码可能更大）。下载跑在模块专用的线程池（上限 2 个并发本子）里，不占用事件循环默认执行器；单页解码失败只跳过该页并计入「下载失败 N 页」，不会让整本失败；任务目录在成功、超限、空结果与异常四条路径上都会清理；协程被取消时线程仍在写盘，改为等它跑完再删，避免残留原图或未加密 PDF。

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
├── bilibili_opus/
│   ├── config.json
│   └── handler.py
├── douyin/
│   ├── config.json
│   └── handler.py
├── arxiv/
│   ├── config.json
│   └── handler.py
├── github/
│   ├── config.json
│   └── handler.py
└── jm/
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
| `sender` | object | 当前私聊可能已绑定规范投递地址的消息发送器 |
| `onebot` | object | OneBot 客户端 |
| `target_id` | int | 群号或私聊 QQ 号 |
| `target_type` | str | `"group"` 或 `"private"` |
| `address` | DeliveryAddress / null | 当前物理投递地址；微信私聊为 `wechat:<逻辑QQ号>`，管线发送结果时应优先复用 `sender` |
| `text` | str | 提取的纯文本内容 |
| `message_content` | list[dict] | 原始消息段列表 |
| `extract_xxx_ids` | callable | 提取器函数 |
| `handle_xxx_extract` | callable | 处理器函数 |

## 注册与热重载

`PipelineRegistry` 在初始化时扫描 `pipelines/` 下每个子目录，按 `order` 排序注册。

热重载每 2 秒（可配置）检查 `config.json` 和 `handler.py` 的 mtime + size 快照，检测到变更后等待 500ms 防抖再重载。新增或删除目录也会在重载时生效。

`PipelineRegistry` 监视 `config.json` 和 `handler.py` 的变更。如果只改 `README.md` 不会触发重载。
