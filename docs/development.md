# 扩展与开发

Undefined 欢迎开发者参与共建和进行二次开发！

由于项目核心架构使用了全新的 Skills 系统、Onebot 协议适配层以及多队列并发模型，本篇文档旨在为你提供全面的扩展指导与开发准则。

## 核心目录结构

整体的源码挂载在 `src/Undefined/` 下：

```text
src/Undefined/
├── ai/            # AI 运行时核心组件 (client, prompt, tooling 工具组装, summary 短期摘要, multimodal 多模态)
├── bilibili/      # B站视频流解析、分段下载与异步发送
├── cognitive/     # 认知记忆系统底座 (向量存储, 史官合并/改写, 侧写生成, 任务队列)
├── skills/        # 技能插件核心目录 (存放所有的工具与智能体)
│   ├── tools/           # 基础原子的工具 (独立的功能单元，如读写文件、网络请求等)
│   ├── toolsets/        # 聚合工具集 (分组后的工具组)
│   │   └── cognitive/   # 认知记忆主动暴露工具 (search_events, get_profile 等)
│   ├── agents/          # 智能体 (独立自主的子 AI，负责处理诸如 Web 搜索、文件分析的具体长时任务)
│   └── anthropic_skills/# Anthropic 协议集成的外部 Skills (兼容 SKILL.md 格式)
├── services/      # 核心运行服务 (Queue 任务队列, Command 命令分发, Security 安全防护拦截)
├── utils/         # 通用支持工具组 (包含历史处理、JSON原子读写加锁 IO 操作等)
├── handlers.py    # 最外层 OneBot 消息分流处理层
└── onebot.py      # OneBot WebSocket 客户端核心连接
```

## 开发指南

- **添加新 Agent 与工具**：请参考项目内的详细指南 [src/Undefined/skills/README.md](../../src/Undefined/skills/README.md) 了解如何编写新的功能单元、注册工具和打包一个新的专业 Agent。
- **Agents 开发专版**：[agents/README.md](../../src/Undefined/skills/agents/README.md)
- **Tools 开发专版**：[tools/README.md](../../src/Undefined/skills/tools/README.md)
- **Toolsets 开发专版**：[toolsets/README.md](../../src/Undefined/skills/toolsets/README.md)

### callable.json 共享授权机制

在开发过程中，如何让你的 Agent 具备特定工具的访问权限，或让多个 Agent 进行合作调用？
查看 [callable.md](callable.md) 了解如何通过维护 `callable.json` 来实现：
- 细粒度的工具白名单权限配置。
- 允许特定 Agent 相互调用的灵活授权。

## 开发自检 (代码规范与类型检查)

修改完代码提交之前，请始终进行以下命令确认代码符合质量标准并拦截潜在的类型隐患：

```bash
uv run ruff format .
uv run ruff check .
uv run mypy .
```
> **注意**：项目严格遵守类型注释规范，`mypy .` 通过是代码入库的前提条件。
