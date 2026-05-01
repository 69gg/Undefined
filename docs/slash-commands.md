# 命令系统与斜杠指令

Undefined 提供了一套强大的斜杠指令（Slash Commands）系统。管理员可以通过简单的带前缀的命令（如 `/help`）在群聊或私聊中快速管理机器人状态、查询统计信息或分配权限。

本文档将分为**使用指南**和**自定义开发指南**两部分，帮助你全面掌握命令系统。

---

## 👨‍💻 第一部分：斜杠命令详细使用指南

### 权限与调用说明

- 所有的管理类斜杠命令需要发送者具有管理员或超管权限（在 `config.local.json` 中配置或通过 `/addadmin` 动态添加）。
- 普通用户使用此类命令时会收到权限不足的提示。
- 私聊里只有 `config.json` 显式声明 `"allow_in_private": true` 的命令可直接执行；未开放命令会提示“当前不支持私聊使用”。

### 内置命令列表及详细用法

#### 1. 基础帮助与状态查询
- **/help [命令名]**
  - **说明**：
    - 不带参数时，默认将所有可用命令的快速速查表渲染为图片发送。
    - 带命令名时，默认将该命令的统一格式帮助渲染为图片发送（命令元信息 + 命令目录下 README 文档内容）。
    - 命令目录下 README 会作为 Markdown 渲染到图片中，而不是以源文件文本展示。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `命令名` | 可选 | 目标命令名，支持带或不带 `/`，如 `stats` 或 `/stats` |
    | `-t` | 可选 | 直接发送纯文本帮助，不进行图片渲染 |

  - **示例**：
    ```
    /help
    /help -t
    /help stats
    /help /faq
    /help stats -t
    ```

- **/copyright**
  - **说明**：查看项目版权信息、开源协议和风险免责声明。
  - **别名**：`/license`、`/about`、`/disclaimer`
  - **参数**：无
  - **示例**：
    ```
    /copyright
    /license
    ```

- **/version**
  - **说明**：查看当前 Undefined 版本号与最新版本变更标题。
  - **别名**：`/v`
  - **参数**：无
  - **示例**：
    ```
    /version
    /v
    ```

- **/changelog [list [数量] | show <版本号> | latest]**
  - **说明**：
    - 查看仓库内 `CHANGELOG.md` 维护的版本历史。
    - 不带参数时，默认列最近 8 个版本，只展示版本号与标题，避免刷屏。
    - `show`/`latest` 会展示单个版本的标题、摘要和变更点。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `list` | 可选 | 列出最近多个版本；省略时默认等价于 `/changelog` |
    | `数量` | 可选 | `list` 模式返回的版本数量，默认 8，最大 20 |
    | `show` | 可选 | 查看指定版本详情 |
    | `版本号` | `show` 时必填 | 目标版本号，支持 `v3.2.6` 或 `3.2.6` |
    | `latest` | 可选 | 直接查看最新版本详情 |

  - **返回内容**：
    - `list`：版本号 + 标题的紧凑列表，并提示使用 `/changelog show <version>` 查看详情。
    - `show` / `latest`：版本标题、摘要和 bullet 变更点。
  - **边界行为**：
    - `list` 的数量超过 20 会自动截到 20。
    - 版本不存在、参数格式不合法或 `CHANGELOG.md` 格式异常时，会返回明确错误提示。
  - **示例**：
    ```
    /changelog
    /changelog list 12
    /changelog show v3.2.6
    /changelog show 3.2.6
    /changelog latest
    ```

#### 2. 消息总结与侧写查看

- **/profile [group] [-f|-r|-t] [目标ID]**
  - **说明**：查看用户或群聊的认知侧写。侧写由系统根据聊天历史自动生成和更新。
  - **别名**：`/me`、`/p`
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `group` / `g` | 可选 | 查看群聊侧写（仅群聊可用） |
    | `-f` / `--forward` | 可选 | 合并转发模式输出（默认） |
    | `-r` / `--render` | 可选 | 渲染为图片发送 |
    | `-t` / `--text` | 可选 | 直接文本消息发送 |
    | `<QQ号>` | 可选 | 🔒 超管专用：查看指定用户的侧写 |
    | `g <群号>` | 可选 | 🔒 超管专用：查看指定群聊的侧写 |

  - **行为**：
    - **私聊**：查看自己的用户侧写，不支持 `group` 参数。
    - **群聊**：不带参数查看自己的用户侧写，带 `group` / `g` 查看当前群聊侧写。
    - **超管指定目标**：超级管理员可传入 QQ 号或群号查看任意用户/群的侧写，非超管使用时提示无权限。
    - **输出模式**：默认合并转发；`-r` 渲染为图片；`-t` 直接文本发送。
  - **限流**：普通用户 60 秒，管理员 10 秒，超管无限制。
  - **示例**：
    ```
    /profile           → 查看自己的侧写（合并转发）
    /p -r              → 查看自己的侧写（渲染图片）
    /p -t              → 查看自己的侧写（直接文本）
    /me                → 同上（别名）
    /profile group     → 查看当前群聊的侧写
    /p g               → 同上
    /p 123456          → 🔒 超管：查看QQ号123456的侧写
    /p g 789012        → 🔒 超管：查看群号789012的侧写
    /p 123456 -r       → 🔒 超管：查看指定用户侧写（渲染图片）
    ```

- **/summary [条数|时间范围] [自定义描述]**
  - **说明**：调用消息总结 Agent，拉取指定范围的聊天消息并进行智能总结。
  - **别名**：`/sum`
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `条数` | 可选 | 纯数字，表示总结最近 N 条消息（默认 50，最大 500） |
    | `时间范围` | 可选 | 格式如 `1h`、`6h`、`1d`、`7d`，与条数互斥 |
    | `自定义描述` | 可选 | 总结的重点方向，如"技术讨论"、"项目进展" |

  - **限流**：普通用户 120 秒，管理员 30 秒，超管无限制。
  - **示例**：
    ```
    /summary           → 总结最近 50 条消息
    /summary 100       → 总结最近 100 条消息
    /summary 1d        → 总结过去 1 天的消息
    /summary 50 技术讨论  → 总结最近 50 条，重点关注技术讨论
    /sum 1d 项目进展    → 总结过去 1 天，重点关注项目进展
    ```

#### 3. 统计与分析服务
- **/stats [时间范围] [--ai]**
  - **说明**：生成过去一段时间内 Token 的使用统计数据、模型消耗排行、输入输出比例，并输出可视化图表。默认不启用 AI 分析，显式传 `--ai`（或 `-a`）才会触发。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `时间范围` | 可选 | 统计的回溯时间跨度，不传时默认为最近 7 天 |
    | `--ai` / `-a` | 可选 | 显式启用 AI 智能分析（默认关闭） |

    **时间范围格式：**
    - `Nd`：N 天，如 `7d` = 最近 7 天，`30d` = 最近 30 天
    - `Nw`：N 周，如 `2w` = 最近 14 天
    - `Nm`：N 个月，如 `1m` = 最近 30 天
    - `N`：纯数字，直接解释为天数，如 `14` = 最近 14 天

    > **范围限制**：天数最小为 1 天，最大为 365 天。超出范围自动钳制。无法解析的格式回退到默认值 7 天。

  - **返回内容**：
    - 默认：合并转发消息，包含折线趋势图、模型对比柱状图、输入/输出饼图、模型明细表格和摘要。
    - 传入 `--ai` 时：在以上内容基础上追加 AI 综合分析报告（等待中若 8 分钟内未返回，先发图表，后附超时提示）。
  - **示例**：
    ```
    /stats            → 最近 7 天
    /stats 30d        → 最近 30 天
    /stats 2w         → 最近 14 天
    /stats 1m         → 最近 30 天
    /stats 14         → 最近 14 天
    /stats --ai       → 最近 7 天并启用 AI 分析
    /stats 30d --ai   → 最近 30 天并启用 AI 分析
    ```

#### 4. 权限管理 (动态 Admin)
通过指令动态管理管理员列表，变更会自动持久化到 `config.local.json`，无需重启。超管（Superadmin）拥有最高权限，由配置文件的 `core.super_admins` 静态定义。

- **/lsadmin**
  - **说明**：列出当前所有的系统超级管理员和动态添加的管理员。
  - **参数**：无
  - **返回内容**：超级管理员 QQ 号 + 动态管理员 QQ 列表（无则提示"暂无其他管理员"）。
  - **示例**：`/lsadmin`

- **/addadmin \<QQ号\>**
  - **说明**：将指定 QQ 号添加为动态管理员。**（注：仅 Superadmin 可执行此操作）**。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `QQ号` | 必填 | 目标用户的 QQ 号，必须为纯数字 |

  - **边界行为**：
    - 若 QQ 号不是数字，返回格式错误提示。
    - 若目标已是管理员（含超管），返回"已经是管理员了"提示。
  - **示例**：`/addadmin 123456789`

- **/rmadmin \<QQ号\>**
  - **说明**：移除指定 QQ 的动态管理员权限。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `QQ号` | 必填 | 目标用户的 QQ 号，必须为纯数字 |

  - **边界行为**：
    - 若目标是超级管理员，操作被拒绝（无法通过此命令移除超管）。
    - 若目标本身不是管理员，返回"不是管理员"提示。
  - **示例**：`/rmadmin 123456789`

#### 5. 本地群级 FAQ 系统
用于对常见问题（FAQ）进行检索和管理。FAQ 不必每次请求 AI 大模型，极大地节省 Token 并加快响应。

- **/faq [子命令] [参数]**（别名 `/f`）
  - **说明**：FAQ 管理统一入口，支持子命令和自动推断。
  - **子命令**：

    | 子命令 | 用法 | 权限 | 说明 |
    |--------|------|------|------|
    | `ls` | `/faq ls` | 公开 | 列出当前群组所有 FAQ 条目（最多 20 条） |
    | `view` | `/faq view <ID>` | 公开 | 查看指定 ID 的 FAQ 完整内容 |
    | `search` | `/faq search <关键词>` | 公开 | 按关键词搜索 FAQ（最多 10 条） |
    | `del` | `/faq del <ID>` | 管理员 | 删除指定 ID 的 FAQ |

  - **自动推断**：无需显式写子命令，系统自动推断意图：
    - 无参数 `/faq` → 列表（ls）
    - 参数为 ID 格式（如 `20241205-001`）→ 查看（view）
    - 参数为非 ID 格式（如 `登录`）→ 搜索（search）
    - 显式子命令优先，不会被推断覆盖
  - **示例**：
    - `/faq` — 列出所有 FAQ
    - `/faq 20241205-001` — 查看 FAQ（自动推断为 view）
    - `/faq 登录` — 搜索 FAQ（自动推断为 search）
    - `/faq del 20241205-001` — 删除 FAQ（需管理员）

#### 6. 排障与反馈
- **/bugfix \<QQ号1\> [QQ号2...] \<开始时间\> \<结束时间\>**
  - **说明**：从群历史记录中抓取指定用户在指定时间段内的消息（包含文字、图片的 OCR 描述），交给 AI 进行分析并生成 Bug 修复报告，结果自动存入 FAQ 库。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `QQ号1 [QQ号2...]` | 必填 | 一个或多个目标用户 QQ 号（纯数字，空格分隔） |
    | `开始时间` | 必填 | 格式严格为 `YYYY/MM/DD/HH:MM`，如 `2024/12/01/09:00` |
    | `结束时间` | 必填 | 格式同上，或填写 `now` 表示截止到当前时刻 |

  - **边界行为**：
    - 总参数少于 3 个时，返回用法提示。
    - QQ 号或时间格式解析失败时，分别返回对应的格式错误提示。
    - 指定时间段内无记录时，返回"未找到符合条件的对话记录"。
    - 历史消息一次最多拉取 2500 条。
  - **示例**：
    ```
    /bugfix 123456 2024/12/01/09:00 now
    /bugfix 111111 222222 2024/12/01/09:00 2024/12/01/18:00
    ```

#### 7. Naga 集成管理

> **⚠️ 此功能面向与 NagaAgent 对接的高级场景，普通用户不建议开启。** 需要在 `config.toml` 中同时启用 `[api].enabled`、`[features].nagaagent_mode_enabled` 和 `[naga].enabled`。

- **/naga \<子命令\> [参数]**
  - **说明**：NagaAgent 绑定管理。当前只保留发起绑定和解绑两个子命令。
  - **前置条件**：`api.enabled = true`、`features.nagaagent_mode_enabled = true` 且 `naga.enabled = true`。

  **子命令列表**：

  | 子命令 | 权限 | 作用域 | 说明 |
  |--------|------|--------|------|
  | `bind <naga_id>` | 公开 | 仅群聊 | 在当前白名单群提交绑定申请，生成 `bind_uuid` 并发送到 Naga 端等待回调确认 |
  | `unbind <naga_id>` | 超管 | 群聊/私聊 | 吊销当前绑定，并 best-effort 通知远端同步解绑 |

  **权限模型**：`bind` 子命令配置 `permission: public` + `allow_in_private: false`（仅群聊可用），`unbind` 子命令配置 `permission: superadmin`（仅超管可用），均在 `config.json` 的 `subcommands` 中声明，分发层自动检查。

  - **示例**：
    ```
    /naga bind alice           ← 群内普通用户发起绑定
    /naga unbind alice         ← 超管解绑（私聊或白名单群均可）
    ```

  - **额外行为**：
    - 群聊场景下，所有子命令仅在 `naga.allowed_groups` 白名单内的群可用，非白名单群静默忽略。
    - 私聊场景下不受 `allowed_groups` 限制，但仍要求当前进程的 Runtime API 已启用。
    - `bind` 的成功提示只代表“本地已记录并尝试提交到 Naga 端”，真正生效要等 `bind/callback` 回调确认。
    - `unbind` 成功后会私聊通知绑定用户，并尝试调用远端 `bind/revoke` 接口同步状态。

---

## 🛠️ 第二部分：如何自定义/扩展新的斜杠命令？

Undefined 具有可插拔的指令解析层，所有的指令逻辑实现均放在 `src/Undefined/skills/commands/` 目录下（作为一项特殊的核心系统技能存在）。

开发一个新命令极为简单，只需几行代码即可完成自动注册、权限鉴定要求和参数解析。

### 命令系统的核心结构

```text
src/Undefined/
├── changelog.py          # CHANGELOG.md 解析与查询公共模块
├── services/commands/
│   ├── __init__.py
│   ├── context.py        # 核心上下文 (CommandContext) 定义
│   └── registry.py       # 命令注册表 (CommandRegistry) 和 Meta 定义
└── skills/commands/      # 具体的所有指令实现存放目录
    ├── __init__.py
    ├── changelog/        # 内置命令：版本历史查询
    ├── version/          # 内置命令：版本号与最新变更标题
    ├── help/             # 内置命令：基础帮助
    ├── copyright/        # 内置命令：版权与免责声明
    ├── faq/              # 内置命令：FAQ增删改查
    └── my_custom_cmd/    # 👈 你新建的自定义命令目录（需要包含 config.json 和 handler.py）
```

### 1. 编写自定义命令的基本模板

在 `skills/commands/` 目录下新建一个你的命令大类目录，例如 `skills/commands/hello_world/`，然后在里面创建 `config.json`、`handler.py` 和 `README.md`。

如果命令需要读取仓库级文档或共享数据源，建议像 `/changelog` 一样先把解析逻辑抽到公共模块中，再让命令层只负责参数解析和文本格式化。这样后续即使再接一个 tool 或 API，也不用重复解析同一份文档。

#### A. 配置声明 (`config.json`)
```json
{
    "name": "hello",
    "description": "向群里的盆友问个好",
    "permission": "admin",
    "allow_in_private": true,
    "rate_limit": {
        "user": 10,
        "admin": 5,
        "superadmin": 0
    },
    "show_in_help": true,
    "order": 100,
    "aliases": ["hi", "helloworld"],
    "subcommands": {
        "list": { "description": "列出打招呼记录", "permission": "public" },
        "greet": { "description": "执行打招呼", "args": "<目标>", "permission": "admin" }
    },
    "inference": {
        "default": "greet",
        "rules": [
            { "pattern": "^[a-z]+$", "subcommand": "greet" }
        ],
        "fallback": "greet"
    }
}
```
*提示： `permission` 可选 `public` / `admin` / `superadmin`。*
*提示： `allow_in_private` 控制该命令是否允许在私聊中通过 `/命令` 直接触发，默认 `false`。*
*提示： `rate_limit` 单独指定各级使用者的独立调用冷却拦截秒级时间（0代表无限制）。*
*提示：可选字段 `subcommands` 为子命令声明，每个子命令可独立配置 `description`（必填）、`permission`、`allow_in_private`、`rate_limit`、`args`（参数格式，用于帮助展示）；缺省值继承父命令。*
*提示：可选字段 `inference` 为自动推断配置，`default` 为无参数时推断的子命令，`rules` 为正则匹配列表（按顺序匹配 `args[0]`），`fallback` 为规则都不命中时的兜底子命令。*
*提示：可选字段 `help_footer` 为字符串数组，主要用于 `/help` 这类命令在列表页尾部输出固定提示文案。*

#### B. 执行逻辑 (`handler.py`)
```python
# src/Undefined/skills/commands/hello_world/handler.py
import logging
from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

async def execute(args: list[str], context: CommandContext) -> None:
    # args 为空格分割的参数列表
    if not args:
        target = "世界"
    else:
        target = " ".join(args)
        
    # 执行回复动作
    await context.sender.send_group_message(
        context.group_id, 
        f"👋 你好, {target}! 这个命令是由 {context.sender_id} 触发的。"
    )
```

#### C. 说明文档 (`README.md`)
`README.md` 会被 `/help <command>` 自动读取并作为 Markdown 渲染到统一帮助图片中。若需要纯文本可使用 `/help <command> -t`。建议保持文档简洁、可读、结构稳定（推荐包含“功能 / 用法 / 参数 / 示例 / 说明”）。

```md
# /hello 命令说明

## 功能
向群友打招呼。

## 用法
- /hello [目标]
```

### 2. 参数 Context (`CommandContext`) 详解

被自动注入的 `ctx` 对象包含当前命令生命周期的所有可用资源：

| 属性 | 类型 | 说明 |
|------|------|------|
| `ctx.group_id` | `int` | 当前接收指令的群组 ID。私聊时这通常会映射为 0 或特定逻辑池。 |
| `ctx.sender_id` | `int` | 发出命令的用户 QQ 号。 |
| `ctx.args` | `list[str]` | 参数列表（用空格切割），例如 `/hello foo bar` 则为 `["foo", "bar"]` |
| `ctx.sender` | `MessageSender` | 消息收发器工具，包含 `send_group_message`, `send_private_message` |
| `ctx.config` | `Config` | 系统的核心配置管理器 |
| `ctx.bot_qq` | `int` | 当前机器人的自身 QQ 号 |
| `ctx.ai` | `AIClient` | 主 AI Client，可以用于进行分析、总结等大模型调用 |
| `ctx.faq_storage` | `FAQStorage` | FAQ 的键值操作入口 |
| `ctx.cognitive_service` | `Any \| None` | 认知侧写服务，可调用 `get_profile(entity_type, entity_id)` |
| `ctx.history_manager` | `Any \| None` | 消息历史管理器，可调用 `get_recent(chat_id, msg_type, start, end)` |

### 3. 可用的 `permission` (权限级别)

命令可以限定谁能执行：

- `"superadmin"`: 仅 `config.toml` 中 `[core].superadmin_qq` 的人可执行。
- `"admin"`: 超级管理员 + `config.local.json` 动态添加的管理员均可执行。
- `"public"`: 群内或私聊中的任何用户均可执行。（注意风控和被滥用刷屏的风险）

> **可见性**：`/help` 会根据当前用户的权限级别过滤命令列表。`superadmin` 权限的命令不会对普通用户显示；`admin` 权限的命令不会对非管理员显示。

### 4. 子命令声明式注册与自动推断

对于拥有多个子命令的复合命令（如 `/faq`），在 `config.json` 中用 `subcommands` 声明各子命令，用 `inference` 配置自动推断逻辑。

#### 子命令声明

```json
{
  "subcommands": {
    "ls":    { "description": "列出所有FAQ" },
    "view":  { "description": "查看FAQ详情", "args": "<ID>" },
    "search":{ "description": "搜索FAQ", "args": "<关键词>" },
    "del":   { "description": "删除FAQ", "permission": "admin", "args": "<ID>" }
  }
}
```

子命令字段（均可选，缺省继承父命令）：
- `description` — 子命令描述（必填）
- `permission` — 权限级别，默认继承父命令
- `allow_in_private` — 是否允许私聊，默认继承父命令
- `rate_limit` — 限流配置，默认继承父命令（仅覆盖指定字段）
- `args` — 参数格式如 `<ID>`，用于 `/help` 详情展示

#### 自动推断

```json
{
  "inference": {
    "default": "ls",
    "rules": [
      { "pattern": "^\\d{8}-\\d{3}$", "subcommand": "view" }
    ],
    "fallback": "search"
  }
}
```

- `default`：无参数时推断为该子命令
- `rules`：正则匹配列表，按顺序匹配 `args[0]`，命中则推断为对应子命令；命中后 args 保留为子命令的参数
- `fallback`：所有规则都不命中时，推断为该子命令，原始参数整体传入

#### 权限与作用域

分发层会自动处理：
- `args[0]` 显式匹配子命令名 → 直接使用该子命令的元信息
- 无匹配则按 `inference` 推断 → 推断出的子命令同样做权限/作用域/限流检查
- 权限检查、作用域检查、限流均在分发层统一完成，handler 无需内部再判断

### 5. 自动注册与生效

你无需去任何主函数写 `import hello_world`！
Undefined 会在运行时自动检测 `skills/commands/` 目录变化并热重载命令（新增目录、修改 `config.json` / `handler.py` / `README.md` 都会生效）。只需保证文件存在并且合法：

```bash
uv run Undefined
```

命令就绪后在群里输入 `/help`，你会看到 `/hello` 出现在列表中；输入 `/help hello` 可以看到你在 `README.md` 里写的详细说明。
