<img src="./data/img/head.jpg" width="276" height="368" alt="MuLi" align=right />

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/) [![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<div align="center">

# Undefined

_A high-performance, highly scalable QQ group and private chat robot based on a self-developed architecture._

> 大鹏一日同风起，扶摇直上九万里。

</div>

## 项目简介

**Undefined** 是一个功能强大的 QQ 机器人框架，旨在提供流畅的群组互动和智能助手体验。基于现代 Python 异步技术栈构建，集成了 AI 对话、网页爬虫、图像渲染等多种能力。

## 核心特性

- **高性能架构**：基于 `asyncio` 和 `aiohttp` 构建，轻松处理高并发消息。
- **智能交互**：集成 LangChain，支持自然语言对话与多模态交互。
- **强大的爬虫能力**：内置 `crawl4ai` 和 `playwright`，支持动态网页内容抓取。
- **丰富的工具集**：包含图像渲染、Markdown 处理等实用工具。
- **OneBot 协议支持**：完美兼容 OneBot V11 协议，易于对接各种前端。

## 安装与部署

### 环境要求

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

复制所有的示例配置文件（.env.example -> .env）并填写你的配置信息（如 API 密钥、数据库连接等）。

```bash
cp .env.example .env
```

请确保在 `.env` 中正确配置了必要的服务地址和密钥。

## 启动运行

```bash
uv run python -m Undefined
```

## 致谢与友链

### NagaAgent

本项目中包含 **NagaAgent** 子模块。Undefined 机器人诞生于 NagaAgent 交流群，并在开发过程中得到了 NagaAgent 作者及社区的大力支持以及积极试用。

- **项目链接**: [NagaAgent](https://github.com/Xxiii8322766509/NagaAgent)

特别感谢 NagaAgent 作者同意将其作为子模块集成到本项目中。

## 开源协议

本项目遵循 [MIT License](LICENSE) 开源协议。
