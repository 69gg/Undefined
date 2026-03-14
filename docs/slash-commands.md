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
    - 不带参数时，显示所有可用命令的快速速查表。
    - 带命令名时，显示该命令的统一格式帮助（命令元信息 + 命令目录下 README 文档内容）。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `命令名` | 可选 | 目标命令名，支持带或不带 `/`，如 `stats` 或 `/stats` |

  - **示例**：
    ```
    /help
    /help stats
    /help /lsfaq
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

#### 2. 统计与分析服务
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

#### 3. 权限管理 (动态 Admin)
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

#### 4. 本地群级 FAQ 系统
用于对常见问题（FAQ）进行检索和管理。FAQ 不必每次请求 AI 大模型，极大地节省 Token 并加快响应。

- **/lsfaq**
  - **说明**：列出当前群组的所有 FAQ 条目（最多显示 20 条，超出部分提示剩余数量）。
  - **参数**：无
  - **返回内容**：每条 FAQ 显示其 ID、标题和创建日期。
  - **示例**：`/lsfaq`

- **/searchfaq \<关键词\>**
  - **说明**：在当前群组的 FAQ 库中按关键词进行全文搜索，最多返回 10 条结果。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `关键词` | 必填 | 支持多词（空格分隔），合并为一个搜索字符串 |

  - **示例**：`/searchfaq 登录问题`

- **/viewfaq \<ID\>**
  - **说明**：查看指定 ID 的 FAQ 完整内容。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `ID` | 必填 | FAQ 的唯一 ID，格式形如 `20241205-001` |

  - **返回内容**：FAQ 标题、ID、分析对象 QQ、时间范围、创建时间和完整正文。
  - **示例**：`/viewfaq 20241205-001`

- **/delfaq \<ID\>**
  - **说明**：删除指定 ID 的 FAQ。需要管理员或超管权限。
  - **参数**：

    | 参数 | 是否必填 | 说明 |
    |------|----------|------|
    | `ID` | 必填 | FAQ 的唯一 ID，格式形如 `20241205-001` |

  - **边界行为**：若 ID 不存在，返回"FAQ 不存在"提示。
  - **示例**：`/delfaq 20241205-001`

#### 5. 排障与反馈
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

#### 6. Naga 集成管理

> **⚠️ 此功能面向与 NagaAgent 对接的高级场景，普通用户不建议开启。** 需要在 `config.toml` 中同时启用 `[features].nagaagent_mode_enabled` 和 `[naga].enabled`。

- **/naga \<子命令\> [参数]**
  - **说明**：NagaAgent 绑定管理。通过子命令完成绑定申请、审批、吊销和查询。
  - **前置条件**：`features.nagaagent_mode_enabled = true` 且 `naga.enabled = true`。

  **子命令列表**：

  | 子命令 | 权限 | 作用域 | 说明 |
  |--------|------|--------|------|
  | `bind <naga_id>` | 公开 | 仅群聊 | 在当前群提交绑定申请，记录 QQ 号和群号 |
  | `approve <naga_id>` | 超管 | 群聊/私聊 | 通过绑定申请，生成 scoped token 并同步到 Naga |
  | `reject <naga_id>` | 超管 | 群聊/私聊 | 拒绝绑定申请 |
  | `revoke <naga_id>` | 超管 | 群聊/私聊 | 吊销已有绑定并通知 Naga 删除 token |
  | `list` | 超管 | 群聊/私聊 | 列出所有活跃绑定 |
  | `pending` | 超管 | 群聊/私聊 | 列出待审核申请 |
  | `info <naga_id>` | 超管 | 群聊/私聊 | 查看绑定详情（token 脱敏显示） |

  **权限模型**：命令入口 `config.json` 声明 `"permission": "public"`（允许所有人触发），实际权限由 `scopes.json` 按子命令细粒度控制（详见下方"scopes.json 子命令权限"一节）。

  - **示例**：
    ```
    /naga bind alice           ← 群内普通用户提交绑定
    /naga approve alice        ← 超管通过（私聊或群聊均可）
    /naga reject alice         ← 超管拒绝
    /naga revoke alice         ← 超管吊销
    /naga list                 ← 超管查看所有绑定
    /naga pending              ← 超管查看待审核列表
    /naga info alice           ← 超管查看详情
    ```

  - **额外行为**：
    - 群聊场景下，所有子命令仅在 `naga.allowed_groups` 白名单内的群可用，非白名单群静默忽略。
    - 私聊场景下不受 `allowed_groups` 限制。
    - `approve` 成功后会自动调 Naga API 同步 token 并私聊通知申请人。
    - `reject` 成功后私聊通知申请人。
    - `revoke` 成功后调 Naga API 删除 token。
    - `bind` 提交后自动私聊通知超管。

---

## 🛠️ 第二部分：如何自定义/扩展新的斜杠命令？

Undefined 具有可插拔的指令解析层，所有的指令逻辑实现均放在 `src/Undefined/skills/commands/` 目录下（作为一项特殊的核心系统技能存在）。

开发一个新命令极为简单，只需几行代码即可完成自动注册、权限鉴定要求和参数解析。

### 命令系统的核心结构

```text
src/Undefined/
├── services/commands/
│   ├── __init__.py
│   ├── context.py        # 核心上下文 (CommandContext) 定义
│   └── registry.py       # 命令注册表 (CommandRegistry) 和 Meta 定义
└── skills/commands/      # 具体的所有指令实现存放目录
    ├── __init__.py
    ├── help/             # 内置命令：基础帮助
    ├── copyright/        # 内置命令：版权与免责声明
    ├── faq/              # 内置命令：FAQ增删改查
    └── my_custom_cmd/    # 👈 你新建的自定义命令目录（需要包含 config.json 和 handler.py）
```

### 1. 编写自定义命令的基本模板

在 `skills/commands/` 目录下新建一个你的命令大类目录，例如 `skills/commands/hello_world/`，然后在里面创建 `config.json`、`handler.py` 和 `README.md`。

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
    "aliases": ["hi", "helloworld"]
}
```
*提示： `permission` 可选 `public` / `admin` / `superadmin`。*
*提示： `allow_in_private` 控制该命令是否允许在私聊中通过 `/命令` 直接触发，默认 `false`。*
*提示： `rate_limit` 单独指定各级使用者的独立调用冷却拦截秒级时间（0代表无限制）。*
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
`README.md` 会被 `/help <command>` 自动读取并拼接到统一帮助模板中，建议保持简洁、可读、结构稳定（推荐包含“功能 / 用法 / 参数 / 示例 / 说明”）。

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

### 3. 可用的 `permission` (权限级别)

命令可以限定谁能执行：

- `"superadmin"`: 仅 `config.toml` 中 `[core].superadmin_qq` 的人可执行。
- `"admin"`: 超级管理员 + `config.local.json` 动态添加的管理员均可执行。
- `"public"`: 群内或私聊中的任何用户均可执行。（注意风控和被滥用刷屏的风险）

> **可见性**：`/help` 会根据当前用户的权限级别过滤命令列表。`superadmin` 权限的命令不会对普通用户显示；`admin` 权限的命令不会对非管理员显示。

### 4. `scopes.json` — 子命令权限控制

对于拥有多个子命令的复合命令（如 `/naga`），可以在命令目录下新建 `scopes.json` 文件，按子命令名声明独立的权限与作用域。

#### 基本格式

```json
{
  "bind": "group_only",
  "approve": "superadmin",
  "reject": "superadmin",
  "list": "superadmin",
  "info": "superadmin"
}
```

#### 可用的 scope 值

| 值 | 别名 | 含义 |
|----|------|------|
| `public` | — | 任何人、任何场景均可使用 |
| `admin` | `admin_only` | 仅管理员及超管可使用 |
| `superadmin` | `superadmin_only` | 仅超级管理员可使用 |
| `group_only` | — | 任何人均可使用，但仅限群聊场景 |
| `private_only` | — | 任何人均可使用，但仅限私聊场景 |

**说明**：
- 未在 `scopes.json` 中列出的子命令默认视为 `superadmin`。
- `scopes.json` 由命令 handler 自行加载和校验，注册表不直接读取。
- 使用 `group_only`/`private_only` 时，scope 同时隐含 **权限为 public**（只限制场景，不限制身份）。

#### handler 中如何使用

在 handler 中加载 scopes.json 并调用检查函数：

```python
import json
from pathlib import Path

_SCOPES_FILE = Path(__file__).parent / "scopes.json"

_SCOPE_ALIASES: dict[str, str] = {
    "admin_only": "admin",
    "superadmin_only": "superadmin",
}

def _load_scopes() -> dict[str, str]:
    try:
        with open(_SCOPES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}

def _check_scope(subcmd: str, sender_id: int, context) -> str | None:
    """返回错误提示或 None 表示通过。"""
    scopes = _load_scopes()
    raw = scopes.get(subcmd, "superadmin")
    scope = _SCOPE_ALIASES.get(raw, raw)

    if scope == "group_only":
        return "该子命令仅限群聊使用" if context.scope != "group" else None
    if scope == "private_only":
        return "该子命令仅限私聊使用" if context.scope != "private" else None
    if scope == "public":
        return None
    if scope == "superadmin" and context.config.is_superadmin(sender_id):
        return None
    if scope == "admin" and (
        context.config.is_admin(sender_id)
        or context.config.is_superadmin(sender_id)
    ):
        return None
    return "权限不足"
```

### 5. 自动注册与生效

你无需去任何主函数写 `import hello_world`！
Undefined 会在运行时自动检测 `skills/commands/` 目录变化并热重载命令（新增目录、修改 `config.json` / `handler.py` / `README.md` 都会生效）。只需保证文件存在并且合法：

```bash
uv run Undefined
```

命令就绪后在群里输入 `/help`，你会看到 `/hello` 出现在列表中；输入 `/help hello` 可以看到你在 `README.md` 里写的详细说明。
