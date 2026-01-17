<table border="0">
  <tr>
    <td width="70%" valign="top">
      <div align="center">
        <h1>Undefined</h1>
        <em>A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture.</em>
        <br/><br/>
        <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.12-blue.svg" alt="Python"></a>
        <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
        <br/><br/>
        <p>大鹏一日同风起，扶摇直上九万里。</p>
      </div>
      <h3>项目简介</h3>
      <p>
        <strong>Undefined</strong> 是一个功能强大的 QQ 机器人平台，采用全新的 <strong>自研 Skills</strong> 架构。基于现代 Python 异步技术栈构建，它不仅提供基础的对话能力，更通过内置的五大智能 Agent 实现了代码分析、网络搜索、娱乐互动等多模态能力。
      </p>
    </td>
    <td width="30%">
      <img src="./data/img/head.jpg" width="100%" alt="MuLi" />
    </td>
  </tr>
</table>

### _与 [NagaAgent](https://github.com/Xxiii8322766509/NagaAgent) 进行联动！_

## 立即体验

[点击添加官方实例QQ](https://qm.qq.com/q/cvjJoNysGA)

## 核心特性

- **Skills 架构**：全新设计的技能系统，将基础工具（Tools）与智能代理（Agents）分层管理，支持自动发现与注册。
- **智能 Agent 矩阵**：内置五大专业 Agent，分工协作处理复杂任务：
  - `CodeAnalysisAgent`：代码库分析、文件操作、全局搜索
  - `WebAgent`：智能联网搜索、网页内容抓取与总结
  - `SocialAgent`：Bilibili 视频解析、音乐搜索、社交媒体互动
  - `EntertainmentAgent`：AI 绘图、小说生成、趣味互动
  - `InfoAgent`：天气查询、热搜榜单、实用工具
- **思维链支持**：支持 `Thinking` 模式，提升复杂逻辑推理能力。
- **高并发架构**：基于 `asyncio` 和 `aiohttp`，多队列消息处理机制，轻松应对高并发场景。
- **安全防护**：内置独立的安全模型，实时检测注入攻击与恶意内容。
- **OneBot 协议**：完美兼容 OneBot V11 协议，支持多种前端实现（如 NapCat）。

## 安装与部署

### 环境要求

- Python
- [uv](https://github.com/astral-sh/uv)

### 1. 克隆项目

由于项目中使用了 `NagaAgent` 作为子模块，请使用以下命令克隆项目：

```bash
git clone --recursive https://github.com/69gg/Undefined.git
cd Undefined
```

如果已经克隆了项目但没有初始化子模块：

```bash
git submodule update --init --recursive
```

### 2. 安装依赖

推荐使用 `uv` 进行依赖管理：

```bash
uv sync
```

### 3. 配置环境

复制所有的示例配置文件（.env.example -> .env）并填写你的配置信息。

```bash
cp .env.example .env
```

配置说明：
- **基础配置**：`BOT_QQ`, `SUPERADMIN_QQ`, `ONEBOT_WS_URL`
- **模型配置**：
  - `CHAT_MODEL_*`：主对话模型
  - `VISION_MODEL_*`：视觉识别模型
  - `AGENT_MODEL_*`：Agent 专用模型（建议使用能力更强的模型）
  - `SECURITY_MODEL_*`：安全审核模型
- **功能配置**：`LOG_LEVEL` 等

> 启动项目需要 OneBot 实例，推荐使用 [NapCat](https://napneko.github.io/)。

## 启动运行

```bash
uv run -m Undefined
```

## 使用说明

### 部署后的初始化

机器人启动后会自动连接到 OneBot 实例。如果连接成功，您会在日志中看到机器人 QQ 号及管理员信息。

### Agent 能力展示

机器人通过自然语言自动调用相应的 Agent 完成任务：

#### 1. 🌐 网络与信息 (WebAgent & InfoAgent)
- "搜索一下最近的 AI 新闻"
- "看看今天的微博热搜"
- "查询北京明天的天气"

#### 2. 💻 代码与开发 (CodeAnalysisAgent)
- "分析一下当前项目的目录结构"
- "读取 src/main.py 的内容并解释"
- "在代码库中搜索 'AgentRegistry'"

#### 3. 🎮 娱乐与社交 (SocialAgent & EntertainmentAgent)
- "搜一首周杰伦的歌"
- "找一下 B 站关于 Python 的教程"
- "画一只赛博朋克风格的猫"
- "看一下今天的运势"

### 管理员命令

```bash
/help               # 查看帮助
/lsadmin            # 查看管理员列表
/addadmin <QQ>      # 添加管理员（仅超级管理员）
/rmadmin <QQ>       # 移除管理员（仅超级管理员）
/bugfix <QQ> <Time> # 生成 Bug 修复报告
```

### 消息优先级

系统采用多级优先队列设计：
1. **最高**：超级管理员私聊
2. **高**：普通私聊
3. **中**：群聊被 @
4. **低**：群聊普通消息

## 目录结构

```
src/Undefined/
├── skills/
│   ├── agents/    # 智能体集合 (Web, Code, Social...)
│   └── tools/     # 基础工具 (SendMsg, Render...)
├── config.py      # 配置管理
├── handlers.py    # 消息处理器
└── ai.py          # AI 核心逻辑
```

## 扩展与开发

Undefined 采用模块化的 **Skills** 架构，扩展非常简单：

- **添加工具**: 在 `skills/tools/` 下新建目录，添加 `config.json` 和 `handler.py`。
- **添加 Agent**: 在 `skills/agents/` 下新建目录，定义 `intro.md` 和 `prompt.md`。

## 致谢与友链

### NagaAgent

本项目集成 **NagaAgent** 子模块。Undefined 诞生于 NagaAgent 社区，感谢作者及社区的支持。

> [NagaAgent - A simple yet powerful agent framework.](https://github.com/Xxiii8322766509/NagaAgent)

## 开源协议

本项目遵循 [MIT License](LICENSE) 开源协议。

<div align="center">

**⭐ 如果这个项目对您有帮助，请考虑给我们一个 Star**

</div>