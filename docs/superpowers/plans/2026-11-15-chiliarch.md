# chiliarch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 为 Undefined 提供独立、有正常记忆和侧写的 chiliarch 原生协作渠道。

**Architecture:** 参数化既有会话历史存储，添加可选逻辑身份和普通权限执行器；ChiliarchService 根据配对文件自动管理原生客户端、持久路由和生命周期。技能通过 context 依赖访问服务，复用平台协议和文件助手。

**Tech Stack:** Python 3.11–3.13、asyncio、chiliarch 0.5.x、aiohttp、pytest。

**Spec:** `docs/superpowers/specs/2026-11-15-chiliarch.md`

## Global Constraints

- 未配对时关闭，配对文件出现自动开启、删除自动关闭，单并发；没有 task_workdir 支持。
- chiliarch 为必需依赖，不增加主配置项或环境变量，不修改 config.toml 和配置示例，不另起客户端。
- 不用虚拟 QQ，不继承 WebUI 超管；现有平台权限和旧历史兼容。
- 磁盘 I/O 复用 utils.io；Python 全类型注解，严格 mypy。
- 不连接真实平台、不修改生产 state、不部署、不推送；按用户授权创建签名提交。
- 技能依赖从 context 注入，保持现有 import boundary。

### Task 1: 必需依赖与文件开关

**Files:** pyproject.toml、uv.lock、chiliarch/pair.py、chiliarch/service.py；docs/chiliarch.md、docs/configuration.md；tests/test_chiliarch_pair.py、tests/test_chiliarch_service.py。

**Interfaces:** `data/chiliarch/client.db` 为唯一开关；身份 `chiliarch_main`，单并发。无 Config.chiliarch 或 CHILIARCH_* 配置。

- [x] `chiliarch>=0.5.0,<0.6` 改为必需依赖，更新 lock，移除新增配置并恢复配置示例。
- [x] 配对只原子发布完整凭证文件，不读取或改写主配置；文件变化自动启停，原生心跳和重连由 Undefined 内嵌客户端维护。
- [x] 补配对成功/失败/重复配对与运行中启停测试，简化接入文档。

### Task 2: 通用逻辑身份与当前会话输出

**Files:** context.py、ai/client/ask_loop.py、ai/prompts/builder.py、cognitive/service/service.py、attachments/segments.py、skills/toolsets/messages/send_message/handler.py；tests/test_logical_identity.py。

**Interfaces:** `RequestContext(..., logical_identity: str | None = None)`；extra_context 携带 logical_identity、logical_conversation_id；当前会话使用 `session_send_callback(message: str) -> Awaitable[None]`，普通外部 sender 保留原 ACL。

- [x] 验证逻辑身份 end 入队指向 `user:chiliarch_main`、认知召回同身份，非 QQ frontmatter 不伪造 qq。
- [x] 验证默认 send_message 只进入当前逻辑回调，显式 qq/group/wechat 仍原路由与 ACL；附件按身份及会话隔离。
- [x] 最小修改上下文传播/认知身份选择，保留数字身份与 WebUI 行为；运行相关回归测试。

### Task 3: 原生渠道、会话及协作工具

**Files:** api/webchat_store.py、新增 channels/ 与 chiliarch/；main.py、api/_context.py、api/app.py、skills/toolsets/chiliarch/；tests/test_chiliarch_service.py、test_chiliarch_tools.py。

**Interfaces:** `ChiliarchService(runtime, *, state_path=DEFAULT_STATE_PATH)` 提供 start/stop/status/invoke；state_path 仅用于内部依赖注入，不通过主配置暴露。从 runtime 注入 ai、sender、history、onebot、scheduler；技能调用 `context['chiliarch_service'].invoke(action, arguments, context)`。

- [x] 参数化历史存储的目录、身份、显示名与迁移开关，默认 WebUI 无变化；增加普通权限逻辑会话执行器。
- [x] 原生 handler 共享容量执行任务和本地普通轮次，拒绝 workdir；继续任务持久复用会话。
- [x] 持久路由先于 outbox；处理总管普通消息、关联回信、同伴消息、迟到回复和 interrupted。
- [x] 实现 status/contact/request/result、协作、回执、等待、共享文件工具，复用原生 Mailbox；缓存文件登记 attachment UID。
- [x] 接 main 生命周期和 Runtime 状态路由，跨 QQ/微信/WebUI 提供 context 服务资源。
- [x] mock 平台与临时 state 测去重、取消、中断、降级、身份权限、路由重启、文件；同步 README/development/tool docs。

### Task 4: 集成检查

- [x] 审查任务间接口和全量 diff，修复行为/生命周期问题。
- [x] `uv run pytest tests/`；`uv run ruff check .`；`uv run ruff format --check .`；`uv run mypy .`；`uv build --wheel`。
- [x] 在此清单记录实际结果与未能验证的外部条件，交付本地可审查实现。

## 实施结果（2026-11-15）

- 初版完成独立身份、记忆与侧写、会话、回信关联、协作、文件和 Runtime 鉴权状态 API；全量 4698 passed、2 skipped，覆盖率 70.39%，随后签名提交为 `596f4eb2`。
- 用户收敛接入流程：必需依赖、一次配对、文件自动开关，不添加配置或外部维护进程；介绍和配对凭证由官方 state 保存。
- 重配对按平台/agent 身份隔离业务关联与游标，历史保留；吊销后不反复重连或自行重配对。
- 本次定向回归 47 passed；全量 `uv run pytest tests/ --cov --cov-report=term`：4693 passed、2 skipped，覆盖率 70.63%。
- 全仓 Ruff check、Ruff format --check、严格 mypy（864 个源文件）、uv lock --check 和 wheel 构建通过；wheel 中 chiliarch 为无 extra 条件的必需依赖。
- 配置示例与配置模块已恢复至渠道接入前版本；配对成功、失败与取消均不改写主配置。删除配对文件后停止连接和在途工作，并清理孤立 WAL，避免新配对回放旧消息。
- 测试使用临时 state 与模拟上游，不代表真实平台或模型验收；没有修改生产 state、部署或推送。
