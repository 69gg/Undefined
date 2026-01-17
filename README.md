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
        <strong>Undefined</strong> 是一个功能强大的 QQ 机器人框架，旨在提供流畅的群组互动和智能助手体验。基于现代 Python 异步技术栈构建，集成了 AI 对话、网页爬虫、图像渲染等多种能力。
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

> 启动项目需要OneBot实例，推荐使用 [NapCat](https://napneko.github.io/)。

## 启动运行

```bash
uv run python -m Undefined
```

## 使用说明

### 部署后的初始化

机器人启动后会自动连接到 OneBot 实例。如果连接成功，您会在日志中看到机器人 QQ 号、超级管理员和管理员列表的信息。

```
[INFO] Undefined.main: 机器人 QQ: 123456789
[INFO] Undefined.main: 超级管理员: 987654321
[INFO] Undefined.main: 管理员 QQ: [111111111, 222222222]
```

### 基本命令

在 QQ 群组或私聊中，您可以使用以下命令与机器人交互：

#### 查看帮助
```
/help
```
显示所有可用命令的帮助信息。

#### 管理员管理
```
/addadmin <QQ号>       # 添加新管理员（仅超级管理员）
/rmadmin <QQ号>        # 移除管理员（仅超级管理员）
/lsadmin              # 查看当前管理员列表
```

#### FAQ 功能
```
/searchfaq <关键词>    # 搜索 FAQ 条目
/lsfaq                # 列出当前群组的所有 FAQ
/viewfaq <ID>         # 查看指定 FAQ 的详细内容，例：/viewfaq 20241205-001
/delfaq <ID>          # 删除 FAQ（仅管理员）
```

#### 诊断工具
```
/bugfix <QQ号1> [QQ号2] ... <开始时间> <结束时间>
```
分析与指定用户在指定时间段内的对话，生成 Bug 修复报告。
- 支持指定多个 QQ 号（空格分隔）
- 时间格式：`YYYY/MM/DD/HH:MM`
- 结束时间可用 `now` 表示当前时间
- 示例：`/bugfix 123456 2024/12/01/09:00 now`
- 仅限管理员使用

### 主要功能模块

#### 1. 智能对话与 AI 助手
- 通过自然语言与机器人交互
- 支持多轮对话和上下文理解
- 集成 LangChain 框架，支持自定义 AI 模型

#### 2. 工具集系统
机器人内置丰富的工具集，包括但不限于：

| 工具 | 功能 |
|------|------|
| `web_search` | 网络搜索 |
| `weather_query` | 天气查询 |
| `bilibili_search` | B 站视频搜索 |
| `music_global_search` | 全球音乐搜索 |
| `news_tencent` | 腾讯新闻爬取 |
| `baiduhot` / `weibohot` / `douyinhot` | 各平台热门信息 |
| `render_html` / `render_and_send_image` | HTML/图片渲染 |
| `crawl_webpage` | 网页爬虫 |
| `analyze_multimodal` | 多模态分析（AI 图像分析） |
| `gold_price` | 黄金价格查询 |
| `horoscope` | 星座查询 |

#### 3. 消息管理与历史记录
- 机器人自动跟踪群组对话历史
- 支持查询特定时间段的消息
- 用于 AI 对话的上下文学习

#### 4. 安全防护
- 内置注入攻击检测系统
- 自动识别潜在的恶意提示词
- 异常行为处理和回复生成

### 消息处理优先级

机器人采用多队列架构处理消息，以支持高并发场景：

| 优先级 | 处理队列 | 说明 |
|--------|---------|------|
| 最高 | 超级管理员私聊 | 超级管理员的私聊消息优先处理 |
| 高 | 普通私聊 | 非管理员的私聊消息 |
| 中 | 群聊被 @ | 群组内被机器人 @ 的消息 |
| 最低 | 群聊普通 | 群组内的普通消息 |

### 日志与监控

机器人生成的日志文件位于 `logs/bot.log`，支持自动轮转。可通过 `.env` 配置日志相关参数：

```env
LOG_LEVEL=INFO                    # 日志级别（DEBUG/INFO/WARNING/ERROR）
LOG_FILE_PATH=logs/bot.log       # 日志文件路径
LOG_MAX_SIZE_MB=10               # 单个日志文件最大大小（MB）
LOG_BACKUP_COUNT=5               # 保留的日志文件备份数量
```

### 数据存储

机器人使用以下存储方式：

- **消息历史**：内存存储（最多保存 100 条记忆记录）
- **内存记录**：`data/memory.json` 文件
- **FAQ 数据**：按群组和 FAQ ID 组织存储
- **动态管理员列表**：`config.local.json` 文件

### 性能建议

- **高并发场景**：机器人基于异步架构，可轻松处理高并发消息
- **外部 API 请求**：使用速率限制器防止请求过快，具体限制规则见配置文件

### 故障排查

#### 无法连接到 OneBot
- 检查 `.env` 中的 `ONEBOT_WS_URL` 是否正确
- 确保 NapCat 或其他 OneBot 实现已启动
- 查看日志是否有连接错误信息

#### AI 请求失败
- 检查 API 密钥是否正确填写在 `.env` 中
- 验证 AI 服务的 API 地址是否可访问
- 查看日志中的具体错误信息

#### 命令无法识别
- 确保在群组或私聊中正确输入命令
- 对于需要权限的命令，确保用户具有相应权限
- 使用 `/help` 查看所有可用命令

### 扩展功能

您可以通过以下方式扩展机器人功能：

1. **添加新工具**：在 `src/Undefined/tools/` 目录下创建新的工具模块
2. **自定义 AI 模型**：修改 `config.py` 中的模型配置
3. **增强数据存储**：扩展 `memory.py` 和 `faq.py` 模块

## 致谢与友链

### NagaAgent

本项目中包含 **NagaAgent** 子模块。Undefined 机器人诞生于 NagaAgent 交流群，并在开发过程中得到了 NagaAgent 作者及社区的大力支持以及积极试用。

> [NagaAgent - A simple yet powerful agent framework for personal assistants, designed to enable intelligent interaction, multi-agent collaboration, and seamless tool integration.](https://github.com/Xxiii8322766509/NagaAgent)

再此特别感谢 NagaAgent 作者同意将其作为子模块集成到本项目中。

## 开源协议

本项目遵循 [MIT License](LICENSE) 开源协议。

<div align="center">

**⭐ 如果这个项目对您有帮助，请考虑给我们一个 Star**

</div>