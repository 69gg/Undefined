# 使用与功能说明

本文档对 Undefined 的功能模块进行系统性介绍。完成[部署配置](deployment.md)并成功与 QQ 端建立连接后，即可通过自然语言或结构化指令使用以下全部能力。

---

## 目录

1. [基础交互方式](#1-基础交互方式)
2. [认知记忆系统](#2-认知记忆系统)
3. [内置智能体 (Agents)](#3-内置智能体-agents)
4. [工具集能力一览 (Toolsets & Tools)](#4-工具集能力一览-toolsets--tools)
5. [定时任务与调度](#5-定时任务与调度)
6. [FAQ 知识库管理](#6-faq-知识库管理)
7. [内置斜杠指令参考](#7-内置斜杠指令参考)
8. [多模型池（私聊模型切换）](#8-多模型池私聊模型切换)
9. [WebUI 与跨平台管理](#9-webui-与跨平台管理)

---

## 1. 基础交互方式

### 私聊场景
在私聊会话中，可以直接向 Bot 发送任意消息，无需附加任何前缀或格式要求。系统会自动维护当前对话的完整上下文。

### 群聊场景
在群聊环境中，Bot 默认仅响应以下方式触发的消息：
- **@提及**：在消息中 `@Bot` 并附带指令内容。
- **指令前缀**：使用 `config.toml` 中配置的前缀（如有）。

> **队列优先级说明**：系统底层采用四级消息队列调度模型，优先级从高到低为：超级管理员 > 私聊 > @提及 > 普通群聊。在群聊高并发场景下，管理请求和直接提及将优先得到响应。

---

## 2. 认知记忆系统

Undefined 搭载了基于 ChromaDB 向量数据库的后台认知系统，无需手动录入，即可实现跨会话的长期上下文追踪。

| 能力 | 说明 |
|---|---|
| **聊天侧写（Profile）** | 系统实时静默分析对话内容，自动提取并持久化用户的偏好、待办、身份与观点等信息，在后续对话中作为参考背景 |
| **历史事件检索** | 基于向量语义检索，支持按用户、群组、时间段查询历史记忆，并应用时间衰减加权排序 |
| **群聊宏观总结** | 可对历史消息进行语义召回与整合，快速梳理出大量消息中的重点内容 |

**示例：**
> *"请回忆一下我们上周讨论过的项目规划内容。"*
> *"请总结一下本群过去三天内讨论的主要话题。"*

---

## 3. 内置智能体 (Agents)

智能体（Agent）是由独立大模型驱动的高自治任务处理器。主 AI 在理解到任务超出自身直接能力范围时，会自动将任务委托给相应的专业 Agent，由其递归调用子工具完成任务后汇报结果。

### `web_agent` — 网络信息检索助手

负责网页搜索和网页内容爬取，能够获取互联网上的实时最新信息。

**子工具**：`grok_search`（Grok 搜索）、`web_search`（通用搜索）、`crawl_webpage`（网页内容提取）

**示例：**
> *"请搜索最近三天关于 DeepSeek 的最新动态并生成摘要。"*
> *"帮我爬取这个网页的主要内容并整理成结构化笔记。"*

---

### `file_analysis_agent` — 文件分析助手

支持对代码、PDF、Word、Excel 等多种格式文件进行解析与分析。用户只需将文件发送至对话中即可。

**子工具**：`analyze_pdf`、`analyze_docx`、`analyze_xlsx`、`analyze_code`、`read_file`

**示例：**
> *"请分析这份 PDF 文档，提取其中第三章的核心数据。"*
> *"请检查这份 Python 代码，找出其中潜在的性能瓶颈。"*

---

### `info_agent` — 信息查询助手

整合了多种公开信息查询能力，覆盖天气、热搜、域名、哔哩哔哩以及学术论文等信息源。

**子工具**：`weather_query`、`*hot`（热搜榜）、`whois`（域名查询）、`bilibili_search`、`bilibili_user_info`、`arxiv_search`

**示例：**
> *"北京明天的天气怎么样？"*
> *"查一下今天的微博热搜前十名。"*
> *"帮我查询 arxiv 上关于 Chain-of-Thought 的最新论文。"*
> *"查一下 B 站 UP 主 xxx 的近期投稿情况。"*

---

### `entertainment_agent` — 娱乐助手

提供运势、小说、随机图片和随机视频等休闲娱乐类功能。

**子工具**：`horoscope`（星座运势）、`novel_search`（小说检索）、`ai_draw_one`（AI 绘图）、`video_random_recommend`（随机视频推荐）

**示例：**
> *"查一下天蝎座今天的运势。"*
> *"随机推荐几个有趣的视频。"*
> *"帮我画一张赛博朋克风格的城市夜景。"*

---

### `code_delivery_agent` — 代码分析与交付助手

支持沙盒级别的代码代写、本地执行验证与自动打包。测试通过后，代码成果会自动打包为 `.zip` 文件并通过 QQ 发送给用户。

**示例：**
> *"请使用 Python 编写一个 HTTP 测速脚本，监听 8080 端口，验证跑通后将整个项目打包发到这个群。"*

---

### `naga_code_analysis_agent` — NagaAgent 代码分析助手

专门用于深度分析 NagaAgent 框架及本项目的源代码结构。

**子工具**：`read_file`、`search_code`、`analyze_structure`

---

## 4. 工具集能力一览 (Toolsets & Tools)

除了通过 Agent 按需调用外，以下工具在对话中均可以通过自然语言直接触发。

### 渲染 (`render.*`)

| 工具 | 说明 |
|---|---|
| `render.render_markdown` | 将 Markdown 文本（含表格、代码块、标题等）渲染为图片发送 |
| `render.render_latex` | 将 LaTeX 数学公式渲染为图片（**依赖系统 TeX 环境**，需提前安装，详见[部署文档](deployment.md#3-安装系统级依赖必装)） |
| `render.render_html` | 将 HTML 内容渲染为图片 |

支持 `embed`（嵌入回复）和 `send`（直接发送）两种图片交付方式。

**示例：**
> *"请把这段数学公式渲染成图片发给我：$E=mc^2$"*
> *"请把下面这份 Markdown 表格渲染成图片。"*

---

### 表情包 (`memes.*`)

| 工具 | 说明 |
|---|---|
| `memes.search_memes` | 支持 `keyword`（关键词精确匹配）、`semantic`（语义联想检索）、`hybrid`（混合模式）三种检索方式 |
| `memes.send_meme_by_uid` | 根据图片统一 uid 以独立消息发送原图表情包 |

两者通常配合使用：先由 `search_memes` 检索到目标表情包的 uid，再由 `send_meme_by_uid` 独立发送原图。

**示例：**
> *"请根据现在的群聊气氛，发一个应景的表情包。"*

---

### 消息操作 (`messages.*`)

| 工具 | 说明 |
|---|---|
| `messages.send_message` | 向当前会话发送消息 |
| `messages.send_private_message` | 向指定用户发送私聊消息 |
| `messages.get_recent_messages` | 获取最近若干条历史消息 |
| `messages.get_messages_by_time` | 按时间范围检索历史消息 |
| `messages.react_message_emoji` | 对指定消息添加表情回应 |
| `messages.send_poke` | 发送戳一戳 |
| `messages.send_text_file` | 将文本内容生成文件后发送 |
| `messages.send_url_file` | 下载指定 URL 的文件后发送 |
| `messages.send_group_sign` | 执行群签到操作 |
| `messages.get_forward_msg` | 获取合并转发消息的内容 |

---

### 群组信息查询 (`group.*`)

| 工具 | 说明 |
|---|---|
| `group.get_member_list` | 获取群成员列表 |
| `group.get_member_info` | 查询指定成员的详细信息 |
| `group.find_member` | 按昵称/备注搜索群成员 |
| `group.get_member_title` | 获取成员群头衔 |
| `group.get_honor_info` | 查询群荣誉（龙王、话唠等） |
| `group.get_member_activity` | 分析群成员活跃度（支持 member_list / history / hybrid 三种数据源模式） |
| `group.rank_members` | 对群成员进行多维度排名 |
| `group.filter_members` | 按条件过滤群成员 |
| `group.detect_inactive_risk` | 检测长期潜水有流失风险的成员 |
| `group.activity_trend` | 分析群活跃度趋势变化 |
| `group.level_distribution` | 统计群成员等级分布 |
| `group.get_files` | 获取群文件列表 |

**示例：**
> *"帮我查一下这个群里近 30 天没说过话的成员有哪些。"*
> *"请列出本群最近发言最多的前 10 名成员。"*

---

### 群聊深度分析 (`group_analysis.*`)

| 工具 | 说明 |
|---|---|
| `group_analysis.analyze_member_messages` | 深度分析指定成员的消息数量、类型分布和活跃时段 |
| `group_analysis.analyze_join_statistics` | 统计群成员加入趋势与留存情况 |
| `group_analysis.analyze_new_member_activity` | 分析新成员加入后的活跃度变化 |

---

### 认知记忆查询 (`cognitive.*`)

| 工具 | 说明 |
|---|---|
| `cognitive.search_events` | 按关键词语义检索历史记忆事件，支持用户、群组、时间段过滤 |
| `cognitive.get_profile` | 获取指定用户的认知侧写画像 |
| `cognitive.search_profiles` | 跨用户语义搜索侧写信息 |

---

### 置顶备忘录 (`memory.*`)

用于管理 AI 的自我约束事项和高优先级待办。此备忘录会在每轮对话时被固定注入上下文（上限 500 条），优先级高于认知记忆。

| 工具 | 说明 |
|---|---|
| `memory.add` | 添加一条置顶备忘（如"用户要求以后用英文回复"） |
| `memory.update` | 更新指定备忘内容 |
| `memory.delete` | 删除指定备忘 |
| `memory.list` | 列出当前所有置顶备忘 |
| `memory.query_archive` | 查询已归档的历史备忘 |
| `memory.search_summaries` | 语义搜索历史备忘 |

> **注意**：用户偏好、身份等长期用户事实请通过对话让 AI 记入**认知记忆**（`cognitive.*`），而非此处。置顶备忘专用于 AI 自身的行为约束与短期高优待办。

---

### 知识库检索 (`knowledge_*`)

如果管理员在 `config.toml` 中配置了知识库，AI 可通过以下工具检索其中的内容：

| 工具 | 说明 |
|---|---|
| `knowledge_semantic_search` | 基于向量语义检索（支持重排序与相关度过滤） |
| `knowledge_text_search` | 基于关键词的精确文本检索 |
| `knowledge_list` | 列出当前可用的知识库 |

---

### 通讯录查询 (`contacts.*`)

| 工具 | 说明 |
|---|---|
| `contacts.query_friends` | 查询 Bot 的好友列表 |
| `contacts.query_groups` | 查询 Bot 所在的群列表 |

---

### 独立原子工具

| 工具 | 说明 |
|---|---|
| `get_current_time` | 获取当前系统时间，支持公历、农历、黄历等多种格式输出 |
| `get_picture` | 获取指定类型的图片（二次元、壁纸、白丝、黑丝、JK、历史上的今天等 10 余种类别） |
| `qq_like` | 给指定 QQ 号的资料卡点赞（默认 10 次） |
| `python_interpreter` | 在隔离的 **Docker 容器**中执行 Python 代码，支持按需安装第三方库，可在执行后自动发送生成的文件（图片、CSV 等） |
| `bilibili_video` | 下载并发送哔哩哔哩视频（支持 BV 号、链接） |
| `arxiv_paper` | 下载并发送 arXiv 论文 PDF（支持 arXiv ID、链接） |
| `fetch_image_uid` | 将指定 URL 的图片下载并转换为系统内部 uid |
| `task_progress` | 向用户发送长任务的阶段性进度通知 |
| `changelog_query` | 查询系统内置版本更新日志 |

**示例：**
> *"请下载 arXiv 论文 2501.01234 并发到这个群。"*
> *"请在 Docker 里安装 matplotlib 后绘制一张正弦函数图像并发给我。"*
> *"帮我给 QQ 号 123456 点 10 个赞。"*

---

## 5. 定时任务与调度

调度器基于标准 crontab 语法，支持三种执行模式，适用于从简单报时到复杂 AI 自主任务的全部场景。

### 执行模式

| 模式 | 描述 | 配置字段 |
|---|---|---|
| **单工具模式** | 定时调用一个指定的工具，传入固定参数 | `tool_name` + `tool_args` |
| **多工具串/并行模式** | 定时依次（serial）或同时（parallel）调用多个工具 | `tools` + `execution_mode` |
| **AI 自我督办模式** | 在触发时刻，以一段自然语言指令唤醒 AI 自主完成任务 | `self_instruction` |

### 自我督办模式示例

这是调度器最灵活的功能：您可以通过自然语言预约将任意复杂的指令投递给"未来的 AI 自己"来执行。

> *"每天上午 9:00，请回顾昨日遗留的待办事项，并把最重要的前三项通过私聊发给我。"*
> *"每周一 08:30，请总结上周群内的高频讨论话题，生成一份周报并发送至群聊。"*
> *"明天晚上 23:00，帮我生成今天的话痨统计图表发到本群。"*（仅执行一次：设置 `max_executions: 1`）

### 任务管理工具

| 工具 | 说明 |
|---|---|
| `scheduler.create_schedule_task` | 创建定时任务，支持 `max_executions`（达到次数后自动删除） |
| `scheduler.update_schedule_task` | 修改任务的触发规则、执行内容或参数 |
| `scheduler.delete_schedule_task` | 删除指定定时任务 |
| `scheduler.list_schedule_tasks` | 列出当前所有定时任务及其运行状态 |

---

## 6. FAQ 知识库管理

Bot 支持在运行时维护一个结构化的群专属 FAQ 知识库，可通过斜杠指令进行增删查操作。

| 指令 | 权限 | 说明 |
|---|---|---|
| `/lsfaq` | 公开 | 列出当前群的全部 FAQ 条目 |
| `/viewfaq <ID>` | 公开 | 查看指定 FAQ 的详细内容 |
| `/searchfaq <关键词>` | 公开 | 按关键词搜索匹配的 FAQ |
| `/delfaq <ID>` | 管理员 | 删除指定 ID 的 FAQ 条目 |

---

## 7. 内置斜杠指令参考

所有斜杠指令均以 `/` 开头，在群聊或私聊中直接输入即可触发。下表基于代码实际配置整理：

| 指令 | 别名 | 权限 | 私聊 | 说明 |
|---|---|---|---|---|
| `/help [命令名]` | — | 公开 | ✅ | 显示命令列表；附带命令名时展示该命令的详细帮助文档 |
| `/version` | `/v` | 公开 | ✅ | 查看当前版本号及最新版本变更标题 |
| `/changelog [子命令]` | `/cl` | 公开 | ✅ | 查看版本更新日志（详见下方说明） |
| `/copyright` | `/about` `/license` `/cprt` | 公开 | ✅ | 查看版权信息与 MIT 许可证声明 |
| `/stats [天数] [--ai]` | — | 公开 | ✅ | 查看 Token 使用统计图表；附加 `--ai` 启用 AI 智能分析报告 |
| `/lsfaq` | — | 公开 | ❌ | 列出当前群的全部 FAQ |
| `/viewfaq <ID>` | — | 公开 | ❌ | 查看指定 FAQ 详情 |
| `/searchfaq <关键词>` | — | 公开 | ❌ | 按关键词搜索 FAQ |
| `/delfaq <ID>` | — | 管理员 | ❌ | 删除指定 FAQ |
| `/bugfix <QQ号> [起止时间]` | — | 管理员 | ❌ | 基于目标用户近期发言生成娱乐性 Bug 修复报告 |
| `/lsadmin` | — | 管理员 | ✅ | 查看系统当前的超管与管理员列表 |
| `/naga <bind\|unbind>` | — | 公开 | ✅ | 绑定或解绑关联的 NagaAgent 实例 |
| `/addadmin <QQ号>` | — | **超级管理员** | ✅ | 将指定用户提权为普通管理员 |
| `/rmadmin <QQ号>` | — | **超级管理员** | ✅ | 撤销指定用户的管理员权限 |

### `/changelog` 子命令详解

```
/changelog                  # 列出最近 8 个版本（版本号 + 标题）
/changelog list <数量>      # 列出更多版本，最大 20 条
/changelog latest           # 展示最新一个版本的完整变更详情
/changelog show <版本号>    # 展示指定版本的完整详情（带或不带 v 均可）
/changelog <版本号>         # 等同于 show
```

### `/stats` 说明

- 默认统计最近 **7 天**的数据，可传入天数参数（允许范围：1 ~ 365 天）。
- 默认仅生成统计图表与数字摘要，**不触发** AI 智能分析。
- 附加 `--ai`（或 `-a`）时，向 AI 发起分析请求；若分析超时，系统会先返回图表与摘要并附带超时提示。
- 普通用户频率限制为每 3600 秒一次；管理员与超级管理员无限制。

### 扩展自定义指令

系统支持热插拔机制，创建对应目录结构并保存文件即刻生效，无需重启服务。详细的开发步骤与参数说明请参阅 [《命令系统与斜杠指令》](slash-commands.md)。

---

## 8. 多模型池（私聊模型切换）

在 `config.toml` 中全局开启 `[features] pool_enabled = true` 后，Bot 支持在多个配置的大模型之间进行灵活调度：

- **自动轮换**：配置 `strategy = "round_robin"` 或 `"random"` 后，私聊请求会自动按策略在池中模型之间切换。
- **手动指定**：在私聊中，可通过发送"选 1"、"选 2"等指令来手动锁定本次使用的模型。

> 群聊场景始终使用主模型，不参与多模型池调度。

完整配置方式及 Agent 模型池说明请参阅 [《多模型池功能》](multi-model.md)。

---

## 9. WebUI 与跨平台管理

Undefined 提供了一套完整的可视化管理控制台，无需修改配置文件或重启服务即可对系统进行动态管理：

- 实时切换底层驱动的大模型（如 GPT-4o、Claude 3.5 Sonnet 等）。
- 在线编辑系统 Prompt 与人格设定面板。
- 监控并干预运行时任务队列与内存状态。
- 查看完整的 Token 消耗统计与调用日志。

WebUI 通过浏览器访问（默认地址 `http://127.0.0.1:8787`，默认密码 `changeme`，**首次启动必须在 `config.toml` 的 `[webui]` 中修改默认密码**）。如需通过手机或其他设备进行远程管理，可使用配套的多端控制台 App，详见 [《跨平台控制台 App》](app.md)。

---

*如需查阅各模块的底层设计原理与 API 集成说明，请参阅本目录下的其余技术文档。*
