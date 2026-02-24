<table border="0">
  <tr>
    <td width="70%" valign="top">
      <div align="center">
        <h1>Undefined</h1>
        <em>A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture.</em>
        <br/><br/>
        <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11--3.13-blue.svg" alt="Python"></a>
        <a href="https://docs.astral.sh/uv/"><img src="https://img.shields.io/badge/uv-auto%20python%20manager-6a5acd.svg" alt="uv"></a>
        <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
        <a href="https://deepwiki.com/69gg/Undefined"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki"></a>
        <br/><br/>
        <p>大鹏一日同风起，扶摇直上九万里。</p>
      </div>
      <h3>项目简介</h3>
      <p>
        <strong>Undefined</strong> 是一个功能强大的 QQ 机器人平台，采用全新的 <strong>自研 Skills</strong> 架构。基于现代 Python 异步技术栈构建，它不仅提供基础的对话能力，更通过内置的多个智能 Agent 实现代码分析、网络搜索、娱乐互动等多模态能力，具备创新的<strong>无阻塞认知记忆系统</strong>。
      </p>
    </td>
    <td width="30%">
      <img src="https://raw.githubusercontent.com/69gg/Undefined/main/img/head.jpg" width="100%" alt="Undefined" />
    </td>
  </tr>
</table>

### _与 [NagaAgent](https://github.com/Xxiii8322766509/NagaAgent) 进行联动！_

---

## ⚡ 立即体验

[点击添加官方实例QQ](https://qm.qq.com/q/cvjJoNysGA)

## ⚡ 核心特性

- **Skills 架构**：全新设计的技能系统，将基础工具（Tools）与智能代理（Agents）分层管理，支持自动发现与注册。
- **Skills 热重载**：自动扫描 `skills/` 目录，检测到变更后即时重载工具与 Agent，无需重启服务。
- **三层分层记忆架构**：创新的分层记忆系统，模拟人类记忆机制——
  - **短期记忆**（`end.memo`）：每轮对话结束自动记录便签备忘，最近 N 条始终注入，保持短期连续性，零配置开箱即用
  - **认知记忆**（`end.observations` + `cognitive.*`）：核心层，AI 在每轮对话中主动观察并提取用户/群聊事实及有价值的自身行为，经后台史官异步改写后存入向量数据库；支持语义检索、时间衰减加权排序、跨群记忆联动与用户/群聊自动侧写，前台零延迟
  - **置顶备忘录**（`memory.*`）：AI 自身的置顶提醒（自我约束、待办事项），每轮固定注入，支持增删改查
  详见 [认知记忆文档](docs/cognitive-memory.md)。
- **配置热更新 + WebUI**：使用 `config.toml` 配置，支持热更新；提供 WebUI 在线编辑与校验。
- **多模型池**：支持配置多个 AI 模型，可轮询、随机选择或用户指定；支持多模型并发比较，选择最佳结果继续对话。详见 [多模型功能文档](docs/multi-model.md)。
- **本地知识库**：将纯文本文件向量化存入 ChromaDB，AI 可通过关键词搜索或语义搜索查询领域知识；支持增量嵌入与自动扫描。详见 [知识库文档](docs/knowledge.md)。
- **访问控制（群/私聊）**：支持 `access.mode` 三种模式（`off` / `blacklist` / `allowlist`）和群/私聊黑白名单；可按策略限制收发范围，避免误触发与误投递。详见 [docs/access-control.md](docs/access-control.md)。
- **并行工具执行**：无论是主 AI 还是子 Agent，均支持 `asyncio` 并发工具调用，大幅提升多任务处理速度（如同时读取多个文件或搜索多个关键词）。
- **智能 Agent 矩阵**：内置多个专业 Agent，分工协作处理复杂任务。
- **callable.json 共享机制**：通过简单的配置文件（`callable.json`）即可让 Agent 互相调用、将 `skills/tools/` 或 `skills/toolsets/` 下的工具按白名单暴露给 Agent，支持细粒度访问控制，实现复杂的多 Agent 协作场景。
- **Agent 自我介绍自动生成**：启动时按 Agent 代码/配置 hash 生成 `intro.generated.md`（第一人称、结构化），与 `intro.md` 合并后作为描述；减少手动维护，保持能力说明与实现同步，有助于精准调度。
- **请求上下文管理**：基于 Python `contextvars` 的统一请求上下文系统，自动 UUID 追踪，零竞态条件，完全的并发隔离。
- **定时任务系统**：支持 Crontab 语法的强大定时任务系统，可自动执行各种操作（如定时提醒、定时搜索），并支持“向未来的自己发指令”（`self_instruction` 自调用模式）。
- **MCP 协议支持**：支持通过 MCP (Model Context Protocol) 连接外部工具和数据源，扩展 AI 能力。
- **Agent 私有 MCP**：可为单个 agent 提供独立 MCP 配置，按调用即时加载并释放，工具仅对该 agent 可见。
- **Anthropic Skills**：支持 Anthropic Agent Skills（SKILL.md 格式），遵循 agentskills.io 开放标准，提供领域知识注入能力。
- **Bilibili 视频提取**：自动检测消息中的 B 站视频链接/BV 号/小程序分享，下载 1080p 视频并通过 QQ 发送；同时提供 AI 工具调用入口。
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
- 🛠️ **[配置与热更新说明](docs/configuration.md)**：从模型切换到 MCP 库挂载，全方位掌握 `config.toml` 的高阶配置。
- 💡 **[交互与使用手册](docs/usage.md)**：包含实用的对话示例、多模态解析用法，以及群管家必备的管理员`/指令`。
- 🛡️ **[访问控制说明](docs/access-control.md)**：教你如何精准配置黑白名单，让机器人的使用范围分毫不差。
- 🧠 **[认知记忆系统详解](docs/cognitive-memory.md)**：黑科技解密——“无阻塞后台史官”是如何将对话内化为向量记忆与用户侧写的。
- 📚 **[本地知识库接入方案](docs/knowledge.md)**：为 AI 挂载本地文本资产，轻松拥抱企业/个人专属 QA。
- 🔄 **[多模型并发竞技](docs/multi-model.md)**：配置多个异构模型，让它们并行运算、同台 PK，从中择优响应。
- ⌨️ **[命令系统与斜杠指令](docs/slash-commands.md)**：查阅所有斜杠指令(`/*`)的详细用法，并学习如何轻松扩展你自己的指令系统。
- 🔧 **[运维脚本](scripts/README.md)**：嵌入模型更换后的向量库重嵌入等维护工具。
- 👨‍💻 **[开发者与拓展中心](docs/development.md)**：代码结构剖析和开发新 Agent 的流程参考及自检命令。
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

# 3. 准备配置文件（请参照 example 按需修改 API URL 和 Key）
cp config.toml.example config.toml

# 4. 启动可视化控制台（首次启动需使用 webui 修改默认密码和参数）
uv run Undefined-webui
```

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

感谢 **NagaAgent** 子模块作者及社区支持：[NagaAgent - A simple yet powerful agent framework.](https://github.com/Xxiii8322766509/NagaAgent)。

<div align="center">
  <strong>⭐ 如果这个项目对您有帮助，请考虑给我们一个 Star</strong>
</div>
