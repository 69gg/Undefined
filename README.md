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
        <strong>Undefined</strong> 是一个功能强大的 QQ 机器人平台，采用全新的 <strong>自研 Skills</strong> 架构。基于现代 Python 异步技术栈构建，它不仅提供基础的对话能力，更通过内置的多个智能 Agent 实现了代码分析、网络搜索、娱乐互动等多模态综合能力。
      </p>
    </td>
    <td width="30%">
      <img src="https://raw.githubusercontent.com/69gg/Undefined/main/data/img/head.jpg" width="100%" alt="Undefined" />
    </td>
  </tr>
</table>

### _与 [NagaAgent](https://github.com/Xxiii8322766509/NagaAgent) 进行联动！_

## 立即体验

[点击添加官方实例QQ](https://qm.qq.com/q/cvjJoNysGA)

## 核心特性

- **Skills 架构**：全新设计的技能系统，将基础工具（Tools）与智能代理（Agents）分层管理，支持自动发现与注册。
- **并行工具执行**：无论是主 AI 还是子 Agent，均支持 `asyncio` 并发工具调用，大幅提升多任务处理速度（如同时读取多个文件或搜索多个关键词）。
- **智能 Agent 矩阵**：内置多个专业 Agent，分工协作处理复杂任务。
- **定时任务系统**：支持 Crontab 语法的强大定时任务系统，可自动执行各种操作（如定时提醒、定时搜索）。
- **思维链支持**：支持开启思维链，提升复杂逻辑推理能力。
- **高并发架构**：基于 `asyncio` 全异步设计，支持多队列消息处理与工具并发执行，轻松应对高并发场景。
- **安全防护**：内置独立的安全模型，实时检测注入攻击与恶意内容。
- **OneBot 协议**：完美兼容 OneBot V11 协议，支持多种前端实现（如 NapCat）。

## 安装与部署

### 方式一：使用 pip 安装（推荐）

如果您只是想使用机器人，推荐直接从 Release 下载安装包或通过 pip 安装。

#### 1. 安装

直接通过 PyPI 安装：

```bash
pip install Undefined-bot
```

或者下载 Release 中的 `.whl` 文件运行：

```bash
pip install /path/to/Undefined_bot-x.x.x-py3-none-any.whl
```

还需要安装浏览器内核（如果尚未安装）：

```bash
playwright install
```

#### 2. 配置与运行

1.  创建一个文件夹作为机器人的**工作目录**。
2.  克隆 [_NagaAgent_ 仓库](https://github.com/Xxiii8322766509/NagaAgent) 至 `./code/NagaAgent`。
3.  在工作目录下创建一个 `.env` 文件，填入您的配置信息（参考下方配置说明或于 Github 中打开 `.env.example` 查看注释）。
4.  在工作目录下打开终端，直接输入命令启动：

```bash
Undefined
```

> **注意**：程序会自动读取当前运行目录下的 `.env` 文件作为配置。

### 方式二：源码部署（开发）

如果您想进行二次开发或调试，请使用此方式。

#### 1. 克隆项目

由于项目中使用了 `NagaAgent` 作为子模块，请使用以下命令克隆项目：

```bash
git clone --recursive https://github.com/69gg/Undefined.git
cd Undefined
```

如果已经克隆了项目但没有初始化子模块：

```bash
git submodule update --init --recursive
```

#### 2. 安装依赖

推荐使用 `uv` 进行依赖管理：

```bash
uv sync
```

#### 3. 配置环境

复制所有的示例配置文件（.env.example -> .env）并填写你的配置信息。

```bash
cp .env.example .env
```

#### 4. 启动运行

```bash
uv run -m Undefined
```

### 配置说明（通用）

无论使用哪种方式，都需要配置 `.env` 文件：

- **基础配置**：`BOT_QQ`, `SUPERADMIN_QQ`, `ONEBOT_WS_URL`
- **模型配置**：
  - `CHAT_MODEL_*`：主对话模型
  - `VISION_MODEL_*`：视觉识别模型
  - `AGENT_MODEL_*`：Agent 专用模型（建议使用能力更强的模型）
  - `SECURITY_MODEL_*`：安全审核模型
- **功能配置**：`LOG_LEVEL` 等

> 启动项目需要 OneBot 实例，推荐使用 [NapCat](https://napneko.github.io/)。

## 使用说明

### 部署后的初始化

机器人启动后会自动连接到 OneBot 实例。如果连接成功，您会在日志中看到机器人 QQ 号及管理员信息。

### Agent 能力展示

机器人通过自然语言自动调用相应的 Agent 完成任务：

#### 1. 网络与信息

- "搜索一下最近的 AI 新闻"
- "看看今天的微博热搜"
- "查询北京明天的天气"

#### 2. 代码与开发

- "分析一下当前项目的目录结构"
- "读取 src/main.py 的内容并解释"
- "在代码库中搜索 'AgentRegistry'"

#### 3. 娱乐与社交

- "搜一首周杰伦的歌"
- "找一下 B 站关于 Python 的教程"
- "画一只赛博朋克风格的猫"
- "看一下今天的运势"

#### 4. 助理与生活

- "提醒我10分钟后喝水"
- "每天早上8点推送一份 AI 科技新闻"
- "每周五下午5点提醒我写周报"

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
│   ├── tools/     # 基础工具 (SendMsg, GetHistory...)
│   └── toolsets/  # 工具集合 (Render, Scheduler...)
├── config.py      # 配置管理
├── handlers.py    # 消息处理器
└── ai.py          # AI 核心逻辑
```

## 扩展与开发

Undefined 采用模块化的 **Skills** 架构，扩展非常简单：

- **添加工具 (Tools)**: 在 `skills/tools/` 下新建目录，添加 `config.json` 和 `handler.py`。
- **添加工具集合 (Toolsets)**: 在 `skills/toolsets/` 下新建分类目录，再创建工具目录，添加 `config.json` 和 `handler.py`。工具注册名称为 `{category}.{tool_name}`。
- **添加 Agent**: 在 `skills/agents/` 下新建目录，定义 `intro.md` 和 `prompt.md`。

详细开发指南请参考 [src/Undefined/skills/README.md](src/Undefined/skills/README.md)。

## 致谢与友链

### NagaAgent

本项目集成 **NagaAgent** 子模块。Undefined 诞生于 NagaAgent 社区，感谢作者及社区的支持。

> [NagaAgent - A simple yet powerful agent framework.](https://github.com/Xxiii8322766509/NagaAgent)

## 开源协议

本项目遵循 [MIT License](LICENSE) 开源协议。

<div align="center">

**⭐ 如果这个项目对您有帮助，请考虑给我们一个 Star**

</div>