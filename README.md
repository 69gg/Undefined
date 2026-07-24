<table border="0">
  <tr>
    <td width="100%" valign="top">
      <div align="center">
        <h1>Undefined</h1>
        <em>QQ and WeChat bot platform with cognitive memory architecture and multi-agent Skills.</em>
        <br/><br/>
        <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11--3.13-blue.svg" alt="Python"></a>
        <a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/uv-auto%20python%20manager-6a5acd.svg" alt="uv"></a>
        <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
        <a href="https://pypi.org/project/Undefined-bot"><img src="https://img.shields.io/pypi/v/Undefined-bot.svg" alt="PyPI"></a>
        <a href="https://deepwiki.com/69gg/Undefined"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
        <br/><br/>
        <p>大鹏一日同风起，扶摇直上九万里。</p>
      </div>
      <h3>项目简介</h3>
      <p>
        <strong>Undefined</strong> 是一个基于 Python 异步架构的高性能机器人平台，以 OneBot V11 接入 QQ，并可通过微信 ClawBot/iLink 接入微信私聊。项目搭载<strong>认知记忆架构</strong>，采用自研 <strong>Skills</strong> 系统，内置多个智能 Agent，支持代码分析、网络搜索、娱乐互动等多模态能力，并提供 <strong>WebUI</strong> 在线管理，以及可连接同一管理服务的 <strong>跨平台 App</strong>。
      </p>
    </td>
  </tr>
</table>

### _与 [NagaAgent](https://github.com/Xxiii8322766509/NagaAgent) 进行联动！_

---

## ⚡ 立即体验

[点击添加官方实例QQ](https://qm.qq.com/q/cvjJoNysGA)

## Release 下载速查

如果只是部署和运行 QQ Bot，通常**不需要**在 GitHub Release 的 Assets 里下载任何文件。推荐按下方[快速开始](#-快速开始-源码模式)使用源码部署；只想快速体验命令行入口时，可使用 `pip install -U Undefined-bot` 或 `uv tool install Undefined-bot`。

Release 里的安装包是可选组件，不是 Bot 服务本体：

| 目标 | 是否需要下载 Release | 选择 |
| --- | --- | --- |
| 部署 / 运行 QQ Bot | 不需要 | 源码部署，启动 `uv run Undefined-webui`；或使用 `pip` / `uv tool` 安装 Python 包 |
| 远程管理已有实例 | 可选 | `Undefined-Console-*`，用于连接 Management API 并打开远程 WebUI |
| 使用原生聊天客户端 | 可选 | `Undefined-Chat-*`，用于连接 Runtime API 聊天 |
| 离线安装 / 镜像缓存 Python 包 | 可选 | `undefined_bot-*.whl` 或 `undefined_bot-*.tar.gz` |

平台文件选择：

| 平台 | 推荐下载 |
| --- | --- |
| Windows x64 | `*-windows-x64-setup.exe`；批量部署或系统管理场景可选 `.msi` |
| macOS Apple Silicon | `*-macos-arm64.dmg` |
| macOS Intel | `*-macos-x64.dmg` |
| Debian / Ubuntu | `*.deb` |
| 其他 Linux x64 | `*.AppImage` |
| Android 常见手机 / 平板 | `*-android-arm64-v8a-release.apk`；旧 32 位设备选 `armeabi-v7a`，模拟器按需选 `x86_64` / `x86` |

Console 和 Chat 都需要连接到已经运行的 Undefined 服务。首次部署请先启动 `Undefined-webui`，完成配置和 Bot 启动后，再按需使用这些客户端连接。

## ⚡ 核心特性

- **Skills 架构**：全新设计的技能系统，将基础工具（Tools）与智能代理（Agents）分层管理，支持自动发现与注册。
- **Tool Search 按需工具加载**：可在 `[skills]` 下设置 `tool_search_enabled = true`，让主 AI 首轮只接收基础工具、虚拟 `tool_search` 和已检索工具的完整 schema，其余能力仅以名称目录提示，并在检索后的下一模型轮加载。该功能默认关闭，只减少模型上下文中的工具声明，不改变本地注册表、会话权限或子 Agent 的私有工具集。详见 [Tool Search 按需工具加载](docs/tool-search.md)。
- **可嵌入 Python 库**：`pip install Undefined-bot` 后可 import 配置、`AIClient`、Skills 与认知记忆等组件，无需启动 Bot CLI。详见 [Python 库 API 参考](docs/python-api.md)。
- **Skills 热重载**：自动扫描 `skills/` 目录，检测到变更后即时重载工具与 Agent，无需重启服务。
- **三层分层记忆架构**：创新的分层记忆系统，模拟人类记忆机制——
  - **短期记忆**（`end.memo`）：每轮对话结束自动记录便签备忘，最近 N 条始终注入，保持短期连续性，零配置开箱即用
  - **认知记忆**（`end.observations` + `cognitive.*`）：核心层，AI 在每轮对话中主动观察并提取用户/群聊事实及有价值的自身行为，经后台史官异步改写后存入向量数据库；支持语义检索、时间衰减加权排序、MMR 多样性去重、跨群记忆联动与用户/群聊自动侧写（合并时注入历史事件防止特征丢失），前台零延迟
  - **置顶备忘录**（`memory.*`）：AI 自身的置顶提醒（自我约束、待办事项），每轮固定注入，支持增删改查
  详见 [认知记忆文档](docs/cognitive-memory.md)。
- **Management-first WebUI**：继续保留 `uv run Undefined-webui` 一键入口；即使 `config.toml` 缺失或未配完，也能先进入管理态补配置、看日志、校验并启动 Bot。
- **微信 ClawBot/iLink 私聊**：可将一个微信帐号映射为逻辑 QQ 身份，共享权限、私聊历史、认知记忆和模型偏好，同时用 `wechat:<QQ号>` 保持物理回复路由隔离；支持 Markdown、图片、文件、视频、原生语音、同一物理会话内的引用收发，以及保序多项目消息模拟的转发投递，并带二维码管理、媒体上传重试、未知来源隔离、高权限身份二次确认和审计。无需安装 OpenClaw 或微信插件；发送原生语音需要系统提供 FFmpeg。详见 [微信 iLink 接入](docs/wechat-ilink.md)。
- **远程管理 + 多端客户端**：浏览器版 WebUI、跨平台 Console（管理客户端）和原生优先 Undefined Chat（聊天客户端）共享同一套 Management / Runtime 服务，支持远程管理，并覆盖 `Windows / macOS / Linux / Android` 发布链路。
  - **Undefined Console**：基于 Tauri v2 的管理客户端，完整管理功能
  - **Undefined Chat**：基于 Tauri v2 + React 19 的原生优先聊天客户端，采用莫兰迪橙色系设计，移植 WebUI webchat 的核心聊天能力并做原生增强：中英双语运行时切换（i18n）、平台抽象层（按真实平台区分桌面/移动布局）、桌面快捷键、系统凭据存储、HTML 正文 sanitize 内联渲染 + 独立预览窗口隔离运行、Android（非 iOS）横屏/平板适配。iOS 暂不作为发布平台
- **Undefined Chat 跨平台原生对话 App**：`apps/undefined-chat/` 提供独立 Tauri v2 + React 19 原生聊天工作台，直连 Runtime API，并以 Runtime 作为会话、历史、任务、附件和事件真源；桌面端支持快捷键、独立 HTML 预览窗口和系统凭据存储，Android 端支持移动布局、生命周期恢复、流式附件上传和 Keystore 安全存储。详见 [Undefined Chat](docs/undefined-chat.md)。
- **Management API + Runtime API 分层**：配置、日志、Bot 启停和管理探针由 Management API 提供；主进程 Runtime API 则专注探针、记忆只读查询、认知侧写检索和 WebUI AI Chat；内部探针的技能统计覆盖可调用工具、工具集、Agent、自动处理管线、斜杠命令与 Anthropic Skills。详见 [docs/management-api.md](docs/management-api.md) 与 [docs/openapi.md](docs/openapi.md)。
- **多模型池**：支持配置多个 AI 模型，可轮询、随机选择或用户指定；支持多模型并发比较，选择最佳结果继续对话。详见 [多模型功能文档](docs/multi-model.md)。
- **本地知识库**：将纯文本文件向量化存入 ChromaDB，AI 可通过关键词搜索或语义搜索查询领域知识；支持增量嵌入与自动扫描。详见 [知识库文档](docs/knowledge.md)。
- **全局表情包库**：收到图片后可异步判定是否为表情包，通过两阶段 LLM 管线生成纯文本描述与标签，支持关键词检索、语义检索和混合检索，并可直接按统一图片 `uid` 发送或插入 `<attachment uid="..."/>`。详见 [表情包库说明](docs/memes.md)。
- **访问控制（群/私聊）**：支持 `access.mode` 三种模式（`off` / `blacklist` / `allowlist`）和群/私聊黑白名单；可按策略限制收发范围，避免误触发与误投递。详见 [docs/access-control.md](docs/access-control.md)。
- **版本变更可查询**：仓库根目录维护 `CHANGELOG.md`，并提供 `/changelog` 命令在运行时查看最近版本和单版本摘要。
- **并行工具执行**：无论是主 AI 还是子 Agent，均支持 `asyncio` 并发工具调用，大幅提升多任务处理速度（如同时读取多个文件或搜索多个关键词）。
- **智能 Agent 矩阵**：内置多个专业 Agent，分工协作处理复杂任务。
- **Undefined 自身代码查阅 Agent**：内置 `undefined_self_code_agent`，可只读查询当前 Undefined 仓库的源码、测试、文档、资源、脚本、配置示例和 App 实现细节；访问范围受白名单约束，不写代码、不运行命令，并与 NagaAgent 代码分析职责分离。
- **callable.json 共享机制**：通过简单的配置文件（`callable.json`）即可让 Agent 互相调用、将 `skills/tools/` 或 `skills/toolsets/` 下的工具按白名单暴露给 Agent，支持细粒度访问控制，实现复杂的多 Agent 协作场景。
- **Agent 自我介绍自动生成**：启动时按 Agent 代码/配置 hash 生成 `intro.generated.md`（第一人称、结构化），与 `intro.md` 合并后作为描述；减少手动维护，保持能力说明与实现同步，有助于精准调度。
- **请求上下文管理**：基于 Python `contextvars` 的统一请求上下文系统，自动 UUID 追踪，零竞态条件，完全的并发隔离。
- **定时任务系统**：支持 Crontab 语法的强大定时任务系统，可自动执行各种操作（如定时提醒、定时搜索），并支持“向未来的自己发指令”（`self_instruction` 自调用模式）。
- **MCP 协议支持**：支持通过 MCP (Model Context Protocol) 连接外部工具和数据源，扩展 AI 能力。
- **Agent 私有 MCP**：可为单个 agent 提供独立 MCP 配置，按调用即时加载并释放，工具仅对该 agent 可见。
- **Anthropic Skills**：支持 Anthropic Agent Skills（SKILL.md 格式），遵循 agentskills.io 开放标准，提供领域知识注入能力。
- **Bilibili 视频提取与分析**：自动检测消息中的 B 站视频链接/BV 号/小程序分享，下载视频并通过 QQ 合并转发；`bilibili_video` 也可只返回附件 UID，供 `file_analysis_agent` 做视频内容分析。
- **可选音乐工具集**：配置独立部署的 [lxmusic2api](https://github.com/69gg/lxmusic2api) 后，主 AI 可搜索歌曲/歌单、浏览热搜与排行榜、读取歌词/封面/评论、跨平台匹配并交付普通音频附件；完整 Track 通过任务内短引用流转，只暴露面向用户的高层 `music.*` 能力，不暴露下载作业生命周期接口。详见 [使用指南](docs/usage.md#音乐-music) 与 [配置说明](docs/configuration.md#4201-lxmusic2api-音乐服务)。
- **arXiv 论文提取、搜索与分析**：自动检测消息中的 arXiv 链接/标识并发送论文信息与 PDF；`arxiv_paper` 也可只返回 PDF 附件 UID，供 `file_analysis_agent` 做文本提取或指定页视觉分析；`arxiv_search` 负责论文检索。
- **GitHub 仓库卡片**：自动检测 GitHub 仓库链接或 `owner/repo` 仓库 ID，获取 public 仓库信息并发送简洁图片卡片，展示头像、简介、stars、forks、issues、contributors 等概览。
- **自动处理管线**：Bilibili、arXiv、GitHub 等自动提取统一运行在 `skills/pipelines` 中，斜杠命令优先级更高；命令输入/输出会写入历史，非命令消息会并行检测和处理命中管线，结果通过统一发送层写入历史并登记附件 UID 后再进入 AI 回复。远程大附件超过 `[attachments].remote_download_max_size_mb` 时只登记 URL 引用，避免无界下载和缓存膨胀。
- **同 sender 短时消息合并**：默认开启。连续发的多条消息会合并到同一轮 AI 调用，AI 一次看到全部意图自行识别"独立请求/修正/打断"；告别"画猫→改成狗"的重复触发与回复打架。主提示词按 batcher 的"当前输入批次"语义适配，关闭该功能可能导致连续补充/修正消息与提示词不匹配，需要单独适配。可选投机预发送让用户停顿时 LLM 提前开跑、新消息可在未发出回复前取消，进一步压低响应延迟。详见 [docs/message-batching.md](docs/message-batching.md)。
- **思维链支持**：支持开启思维链，提升复杂逻辑推理能力。
- **高并发架构**：基于 `asyncio` 全异步设计，支持多队列消息处理与工具并发执行，轻松应对高并发场景。
- **异步安全 I/O**：统一 IO 层通过线程池 + 跨平台文件锁（Linux/macOS `flock`，Windows `msvcrt`）+ 原子写入（`os.replace`）保证并发写入不损坏、且不阻塞主事件循环。
- **安全防护**：内置独立的安全模型，实时检测注入攻击与恶意内容。
- **OneBot 协议**：完美兼容 OneBot V11 协议，支持多种前端实现（如 NapCat）。

> **想详细了解这些特性是如何组织的？请看完整系统架构：** 👉 [`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## 📖 官方文档导航

Undefined 的功能极为丰富，为了让本页面不过于臃肿，我们将各个模块的深入解析与高阶玩法整理成了专题游览图。这里是开启探索的钥匙：

- ⚙️ **[安装与部署指南](docs/deployment.md)**：不管你是需要 `pip` 无脑一键安装，还是源码二次开发，这里的排坑指南应有尽有。
- 📦 **[Python 库 API 参考](docs/python-api.md)**：根包 lazy re-export、`Config.from_mapping` / `set_config`、公共 API 符号表与嵌入示例。
- 🖥️ **[WebUI 使用指南](docs/webui-guide.md)**：管理控制台功能一览——配置编辑、日志查看、认知记忆管理、表情包库、AI 对话与系统监控。
- 🧭 **[Management API 与远程管理](docs/management-api.md)**：WebUI / App 共用的管理接口、认证、配置/日志/Bot 控制与引导探针说明。
- 🛠️ **[配置与热更新说明](docs/configuration.md)**：从模型切换到 MCP 库挂载，全方位掌握 `config.toml` 的高阶配置；库嵌入见 [§2 库嵌入配置](docs/configuration.md#2-库嵌入配置)。
- 🔎 **[Tool Search 按需工具加载](docs/tool-search.md)**：减少主 AI 请求携带的 function schema，说明启用方式、检索语法、请求级生命周期、权限边界及 Chat Completions / Responses 兼容行为。
- 😶 **[表情包系统 (Memes)](docs/memes.md)**：查看表情包两阶段判定管线、统一图片 `uid` 发送机制、检索模式及库存管理说明。
- 💡 **[交互与使用手册](docs/usage.md)**：包含实用的对话示例、多模态解析用法，以及群管家必备的管理员`/指令`。
- 📝 **[版本变更记录](CHANGELOG.md)**：查看按版本整理的更新摘要，也可在运行时使用 `/changelog` 查询。
- 🛡️ **[访问控制说明](docs/access-control.md)**：教你如何精准配置黑白名单，让机器人的使用范围分毫不差。
- 🧠 **[认知记忆系统详解](docs/cognitive-memory.md)**：黑科技解密——“无阻塞后台史官”是如何将对话内化为向量记忆与用户侧写的。
- 📚 **[本地知识库接入方案](docs/knowledge.md)**：为 AI 挂载本地文本资产，轻松拥抱企业/个人专属 QA。
- 🔄 **[多模型并发竞技](docs/multi-model.md)**：配置多个异构模型，让它们并行运算、同台 PK，从中择优响应。
- ⌨️ **[命令系统与斜杠指令](docs/slash-commands.md)**：查阅所有斜杠指令(`/*`)的详细用法，并学习如何轻松扩展你自己的指令系统。
- 🌐 **[Runtime API 与 OpenAPI](docs/openapi.md)**：主进程 Runtime API、鉴权、探针、记忆/侧写查询和运行态集成说明。
- 💬 **[微信 ClawBot / iLink 接入](docs/wechat-ilink.md)**：逻辑 QQ 身份映射、`wechat:<QQ号>` 路由、扫码管理、隔离与媒体能力说明。
- 💬 **[Undefined Chat](docs/undefined-chat.md)**：原生优先 WebChat 客户端说明——莫兰迪橙色系设计、功能对等表、平台差异（桌面快捷键/独立窗口、Android 生命周期）、Runtime 真源、SSE/JSON fallback、安全存储、附件上传和 HTML 预览隔离。
- 🏗️ **[构建指南](docs/build.md)**：Python 包、WebUI、跨平台 App、Android 与 Release 工作流的构建说明。
- 🔧 **[运维脚本](scripts/README.md)**：嵌入模型更换后的向量库重嵌入等维护工具。
- 👨‍💻 **[开发者与拓展中心](docs/development.md)**：代码结构剖析、模块拆分后的目录树、开发新 Agent 的流程参考及自检命令。
  - **[核心技能系统 (Skills) 解析](src/Undefined/skills/README.md)**：全景式掌握什么是 Skills 架构、怎样定制原子工具与子智能体。
  - **[callable.json 共享授权说明](docs/callable.md)**：细粒度管控 Agent 之间的相互调用与工具越权防范。

---

## ⚡ 快速开始 (源码模式)

> 👶 **新手必看**：如果您是首次部署此类项目或不熟悉 Git/环境配置，**强烈建议直接前往 [《详细安装与部署指南》](docs/deployment.md)** 阅读手把手教程，避免遇到常见报错。

以下步骤适合有一定开发经验、想快速跑起项目源码的用户。我们推荐使用现代 Python 构建工具 `uv`。

```bash
# 1. 完整克隆源码库（注意附带 NagaAgent 模块）
git clone --recursive https://github.com/69gg/Undefined.git

# 2. 进入目录并安装项目依赖包
cd Undefined
pip install uv # 若未安装 uv
uv sync            # uv 将自动为你处理兼容的 Python 解释器并安装包
uv run playwright install  # 安装浏览器内核（用于页面截图等能力）

# 3. 启动管理控制台（推荐入口）
uv run Undefined-webui

# 4. 在 WebUI 中补齐/校验配置，然后直接点击启动 Bot
#    如需先手动准备配置，也可以再执行：
# cp config.toml.example config.toml
```

> 浏览器是默认入口；如果你按上方 [Release 下载速查](#release-下载速查)下载了桌面端或 Android 安装包，也可以在完成首轮密码设置后，连接到同一个 Management API 地址进行远程管理。

---

## 作为 Python 库使用

除 Bot CLI 外，Undefined 也可嵌入脚本、测试或其它服务，直接复用 **Skills 注册表**、**认知记忆**、**知识库**、**AIClient** 等运行时（与 CLI 启动链隔离）。

```bash
pip install Undefined-bot   # 源码开发：uv sync
```

```python
import asyncio

# 根包 lazy re-export：与 CLI 共用同一套运行时组件
from Undefined import AgentRegistry, Config, ToolRegistry, set_config

# 内存构建配置，测试/嵌入场景无需 config.toml
cfg = Config.from_mapping(
    {
        "onebot": {"ws_url": "ws://127.0.0.1:3001"},
        "models": {
            "chat": {"api_url": "https://api.example/v1", "api_key": "sk-xxx", "model_name": "gpt-4o-mini"},
            "vision": {"api_url": "https://api.example/v1", "api_key": "sk-xxx", "model_name": "gpt-4o-mini"},
            "agent": {"api_url": "https://api.example/v1", "api_key": "sk-xxx", "model_name": "gpt-4o-mini"},
        },
    },
    strict=False,
)
set_config(cfg)  # opt-in 注入全局单例；CLI 启动链不会调用

# 自动扫描 skills/：tools + toolsets（end / group.* / cognitive.* …）
tools = ToolRegistry()
# 自动扫描 skills/agents/：web_agent、undefined_self_code_agent、code_delivery_agent …
agents = AgentRegistry()

async def main() -> None:
    # 直接调用原子工具，无需启动 OneBot
    lunar_time = await tools.execute(
        "get_current_time",
        {"format": "text", "include_lunar": True},
        context={},
    )
    print(lunar_time)
    print(len(tools.get_schema()), "tools,", len(agents.get_schema()), "agents")

asyncio.run(main())
```

- [Python 库 API 参考](docs/python-api.md) — 根包符号表、稳定子包路径、`AIClient` / `CognitiveService` 等嵌入示例
- [配置详解 — 库嵌入配置](docs/configuration.md#2-库嵌入配置) — `from_mapping` / `Config.builder`
- [开发者与拓展中心](docs/development.md) — 模块结构与自检命令

---

## 风险提示与免责声明

1. **账号风控与封禁风险（含 QQ 账号）**  
   本项目依赖第三方协议端（如 NapCat/Lagrange.Core）接入平台服务。任何因账号风控、功能限制、临时冻结或永久封禁造成的损失，均由实际部署方自行承担。

2. **敏感信息处理风险**  
   请勿使用本项目主动收集、存储、导出或传播敏感信息。因使用者配置不当或违规处理数据导致的合规处罚及连带损失保留追究权力。

3. **合规义务归属**  
   使用者应确保其部署与运营行为符合所在地区法律法规、平台协议及群规。项目维护者不对使用者的具体行为及后果承担连带责任。

## 开源协议与致谢

本项目遵循 [MIT License](LICENSE) 开源协议。

感谢 **NagaAgent** 子模块作者及社区提供的支持与鼓励：[NagaAgent - A simple yet powerful agent framework.](https://github.com/Xxiii8322766509/NagaAgent)！

感谢在开发过程中为我提供各种灵感的群友们！

<div align="center">
  <strong>⭐ 如果这个项目对您有帮助，请考虑给我们一个 Star</strong>
</div>
