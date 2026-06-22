# 扩展与开发

Undefined 欢迎开发者参与共建和进行二次开发！

由于项目核心架构使用了全新的 Skills 系统、Onebot 协议适配层以及多队列并发模型，本篇文档旨在为你提供全面的扩展指导与开发准则。

## 核心目录结构

整体的源码挂载在 `src/Undefined/` 下：

```text
src/Undefined/
├── changelog.py   # CHANGELOG.md 解析与版本查询公共层
├── ai/            # AI 运行时核心
│   ├── client/    # AIClient 组合：setup / queue / ask_loop
│   ├── llm/       # ModelRequester、streaming、thinking、sanitize
│   ├── prompts/   # PromptBuilder、system_context、cognitive 片段
│   └── multimodal/# 多模态检测、解析与分析
├── attachments/   # 附件注册、渲染、作用域隔离
├── arxiv/         # arXiv 论文解析、元信息获取、PDF 下载与发送
├── bilibili/      # B站视频流解析、分段下载与异步发送
├── cognitive/     # 认知记忆系统（service/ 门面 + historian/ 史官后台）
├── config/        # 配置系统（parsers/ 域解析 + load_sections/ 分段加载 + loader shim）
├── handlers/      # OneBot 消息分流（message_flow / poke / repeat / auto_extract）
├── onebot/        # OneBot WebSocket 客户端
├── skills/        # 技能插件核心目录 (存放所有的工具与智能体)
│   ├── tools/           # 基础原子的工具 (独立的功能单元，如读写文件、网络请求等)
│   ├── toolsets/        # 聚合工具集 (分组后的工具组)
│   │   └── cognitive/   # 认知记忆主动暴露工具 (search_events, get_profile 等)
│   ├── agents/          # 智能体 (含 runner/ 通用循环子包)
│   ├── commands/        # 中心化斜杠指令系统 (实现如 /help, /stats, /admin 等平台功能)
│   ├── pipelines/     # 自动提取管线 (bilibili / arxiv / github 等)
│   └── anthropic_skills/# Anthropic 协议集成的外部 Skills (兼容 SKILL.md 格式)
├── api/           # Management API + Runtime API
│   ├── routes/    # 路由子模块 (chat, tools, naga/, system, memes, memory, cognitive, health)
│   ├── app.py     # aiohttp 服务主入口 (薄包装委派到 routes/)
│   └── _openapi.py # OpenAPI 文档生成
├── memes/         # 表情包库 (service + ingest/ + search/ + store + vector_store)
├── services/      # 核心运行服务
│   ├── coordinator/     # AICoordinator 唯一实现（群聊 / 私聊 / 批处理 / 后台任务 mixins）
│   ├── commands/          # CommandDispatcher mixins（stats / bugfix）
│   ├── message_batcher/   # 同 sender 短时合并
│   ├── command.py         # 命令分发门面 + shim 组合
│   ├── queue_manager.py   # 车站-列车队列
│   └── security.py        # 注入检测与速率限制
├── utils/         # 通用支持工具组 (__init__.py 聚合 io/paths/resources；io.py 异步原子读写, history.py, coerce.py 类型强转)
└── py.typed       # PEP 561 类型标记（wheel 通过 pyproject force-include 打包）
```

## 开发指南

- **添加新 Agent 与工具**：请参考项目内的详细指南 [src/Undefined/skills/README.md](../src/Undefined/skills/README.md) 了解如何编写新的功能单元、注册工具和打包一个新的专业 Agent。
- **Agents 开发专版**：[agents/README.md](../src/Undefined/skills/agents/README.md)
- **Tools 开发专版**：[tools/README.md](../src/Undefined/skills/tools/README.md)
- **Toolsets 开发专版**：[toolsets/README.md](../src/Undefined/skills/toolsets/README.md)
- **Commands 开发专版**：[详细斜杠指令开发指南](slash-commands.md)

### CHANGELOG 维护约定

- 仓库根目录的 `CHANGELOG.md` 是正式版本历史的唯一事实来源。
- `src/Undefined/changelog.py` 负责解析和校验这份文档，供 `/changelog` 命令和 `changelog_query` tool 共用。
- 新增或调整版本条目时，不要只改 tag 注释；应同步维护 `CHANGELOG.md`，确保运行时查询、仓库文档和 GitHub Release 说明一致。
- 发布流水线会校验构建版本、tag 版本和 `CHANGELOG.md` 最新版本一致，并从最新 changelog 条目生成 Release notes。

### callable.json 共享授权机制

在开发过程中，如何让你的 Agent 具备特定工具的访问权限，或让多个 Agent 进行合作调用？
查看 [callable.md](callable.md) 了解如何通过维护 `callable.json` 来实现：
- 细粒度的工具白名单权限配置。
- 允许特定 Agent 相互调用的灵活授权。

## 开发自检 (代码规范、类型检查与 Git Hook)

修改完代码提交之前，请始终进行以下命令确认代码符合质量标准并拦截潜在的类型隐患：

```bash
uv run ruff format .
uv run ruff check .
uv run mypy .
uv run pytest tests/
```

如果你改动了跨平台控制台 `apps/undefined-console/`，或改动了 `src/Undefined/webui/static/js/` 里的前端脚本，建议额外执行：

```bash
cd apps/undefined-console
npm install
npm run check
```

### Git Hook

仓库内已经提供可维护的 git hook：

```text
.githooks/pre-commit
.githooks/pre-tag
```

启用方式：

```bash
bash scripts/install_git_hooks.sh
```

启用后：

- `pre-commit` 会执行 Python 的 `ruff + mypy`
- 当提交包含 JS / Tauri / WebUI 前端相关改动时，还会自动执行 `Biome + TypeScript + cargo fmt/check`

> **注意**：项目严格遵守类型注释规范，`mypy .` 通过是代码入库的前提条件；跨平台控制台相关改动则以 `npm run check` 通过为准。

## 注释规范

库化重构期间，各 Track 在拆分与注释 Wave 中须遵守以下 docstring 与行内注释约定。目标：提升可读性、支撑 `fuck-u-code` 注释比例达标（<30%），且**不改变运行时行为**。

### 模块 docstring

每个 `.py` 文件（shim 除外）顶部须有**一行摘要** + 可选段落说明职责边界：

```python
"""OneBot WebSocket 客户端连接管理。

负责与 NapCat/Lagrange 建立 WS 连接、心跳与事件分发；不处理业务消息逻辑。
"""
```

- 使用中文或英文均可，与同目录现有风格保持一致。
- Shim 文件仅保留一行：`# <path>.py — compatibility shim; do not add logic here.`

### 类 docstring

公开类（`class X` 无 leading `_`）须有 docstring，说明**职责**与**主要协作对象**：

```python
class CognitiveService:
    """认知记忆运行时入口。

    协调向量检索、侧写读写与史官后台任务队列；由 main 进程持有单例。
    """
```

- 内部辅助类（`_Foo`、`SkillStats` 等 dataclass）鼓励简短一行说明。
- 禁止复制类型签名（mypy 已覆盖）；重点写「为什么存在」。

### 公开方法 / 函数 docstring

模块级公开函数与类公开方法（无 leading `_`）须有 docstring，推荐 Google 风格精简版：

```python
def get_config(strict: bool = True) -> Config:
    """获取全局配置单例。

    Args:
        strict: 为 True 时缺少必填项则抛错；False 时使用默认值填充。

    Returns:
        已加载的 Config 实例。
    """
```

- `@property` 公开 getter 视同方法。
- 异步公开方法同样适用；注明可能抛出的业务异常（若有）。
- 复杂算法或非 obvious 分支：**行内注释**说明意图，而非复述代码。

### 行内注释

- 仅用于解释**非 obvious 的业务规则**、兼容分支、性能/并发考量。
- 禁止「递增 i」「返回结果」类冗余注释。
- 魔法数字须命名常量或注释来源（配置项名 / 协议字段）。

### Skills handler 统一模板

`skills/tools/**/handler.py`、`skills/toolsets/**/handler.py`、`skills/agents/**/handler.py`、`skills/commands/**/handler.py`、`skills/pipelines/**/handler.py` 在注释 Wave 中统一采用：

```python
"""<工具/Agent/命令/管线的人类可读名称>。

<一句话说明能力边界与主要输入输出；可列 1~3 条 bullet 行为要点。>

config.json 关键字段：<field> — <含义>（若非 obvious）。
"""

from __future__ import annotations

# ... 实现 ...


async def execute(args: dict[str, Any], context: dict[str, Any]) -> Any:
    """执行入口（由 Registry 调用）。

    Args:
        args: LLM tool call 解析后的参数字典。
        context: 运行时注入上下文（sender、session、registry 等）。

    Returns:
        工具结果字符串或结构化 payload；异常由 Registry 捕获并记录。
    """
```

- **禁止**在 handler 注释 Wave 中修改 `config.json`、目录结构或 handler 签名。
- handler 内私有函数 `_foo` 可选一行 docstring；复杂解析逻辑建议补充。

### 注释 Track 自检

注释-only PR 合并前：

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/Undefined/<changed-path>/
uv run pytest tests/  # 全量由 Phase 3 Integrator 执行
```

公共 API 说明见 [`docs/python-api.md`](python-api.md)。
