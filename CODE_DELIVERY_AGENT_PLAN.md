# Code Delivery Agent 详细实施计划（仅规划，不改实现）

## 1. 背景与目标

### 1.1 目标
在 `src/Undefined` 技术栈内新增一个可执行“代码编写 -> 运行验证 -> 打包 -> 发送到群聊/私聊”的 Agent，
用于从指定初始化来源（Git 仓库或空目录）开始完成交付。

### 1.2 明确边界（当前版本）
- 仅覆盖 `src/Undefined`，不涉及 `code/NagaAgent`。
- 不做人审确认流程。
- 不做命令白名单。
- 不做网络白名单，容器全程开网。
- Docker 不做端口映射。
- 打包排除规则由 AI 在调用 `end` 工具时提供（黑名单由 AI 给出）。

### 1.3 核心结果
- 新增 `code_delivery_agent`（可被主 AI 调用）。
- 提供 7 个工具：`read` / `write` / `glob` / `grep` / `run_bash_command` / `todo` / `end`。
- `end` 完成“按黑名单打包并上传到目标群/私聊”。
- 工作目录与容器在任务完成后及时清理。
- 任务内若单次 LLM 请求连续失败达到 5 次，主动向目标群/私聊发送失败通知和失败原因。
- Docker 容器名采用固定前后缀规则，便于启动时扫描与清理残留容器。
- Agent 每次启动前先执行一次“残留兜底清理”：删除 `data/code_delivery/` 下目录与相关 Docker 容器（若存在）。
- 功能实现完成后，补充并更新本仓库相关文档。

---

## 2. 目录与生命周期设计

### 2.1 任务根目录
每次调用 agent 创建唯一任务目录：

`data/code_delivery/{task_uuid}/`

内部结构：
- `workspace/`：项目工作区（AI 读写、构建、打包源）
- `tmpfs/`：宿主侧临时目录（用于与容器临时挂载配合）
- `logs/`：可选执行日志
- `artifacts/`：可选中间产物（最终包也可放此处）

### 2.2 容器挂载
容器内固定路径：
- `/workspace` -> `data/code_delivery/{task_uuid}/workspace`
- `/tmpfs` -> `data/code_delivery/{task_uuid}/tmpfs`

### 2.3 清理策略
- 启动前清理（防中断残留）：
  1. 删除 `data/code_delivery/` 下所有历史任务目录；
  2. 删除名称匹配 code_delivery 命名规则的 Docker 容器（运行中与已退出都处理）。
- 正常结束：`end` 发送完成后，停止并删除容器，清理 `data/code_delivery/{task_uuid}/`。
- 异常结束：handler `finally` 做兜底清理。
- 清理失败仅记录日志，不阻断用户结果返回。

---

## 3. Docker 执行模型

### 3.1 镜像
- 默认镜像：`ubuntu:24.04`（可配置）。

### 3.2 运行方式
每个任务一个容器，生命周期随任务。

建议参数（示意）：
- `docker run -d --rm`
- `-v <task_workspace>:/workspace`
- `-v <task_tmpfs>:/tmpfs`
- `-w /workspace`
- 不加 `-p`（无端口映射）
- 不加 `--network none`（全程开网）

### 3.3 命令执行
- `run_bash_command` 统一走 `docker exec <container> bash -lc "..."`。
- 不在宿主机直接执行用户构建命令。

### 3.4 容器命名规则
- 容器名使用固定格式：`<container_name_prefix><task_uuid><container_name_suffix>`。
- 建议默认：`container_name_prefix = "code_delivery_"`，`container_name_suffix = "_runner"`。
- 启动前残留清理时，依据此前后缀规则匹配并清理相关容器。

---

## 4. Agent API 设计

## 4.1 Agent 名称
`code_delivery_agent`

### 4.2 入参设计
- `prompt: string` 任务目标
- `source_type: "git" | "empty"`
- `git_url?: string`（`source_type=git` 必填）
- `git_ref?: string`（可选，分支/tag/commit）
- `target_type: "group" | "private"`
- `target_id: integer`

### 4.3 prompt 显式要求
在 handler 组装给子 agent 的 `user_content` 时，必须显式写明初始化来源：
- Git 来源：`source_type=git, git_url=..., git_ref=...`
- 空仓来源：`source_type=empty`

目标是让子 agent 不会丢失“从哪里初始化”的关键上下文。

### 4.4 文档与交付约束
- 若 `source_type=empty`，AI 在产出代码时必须补齐项目 `README.md`（不可留空）。
- 任务完成前，AI 必须补全相关文档（至少包含使用方式与运行说明）。
- `end` 前应确保交付内容包含代码与文档两部分，而非只提交代码文件。

---

## 5. 工具集合设计（当前 7 个）

## 5.1 `read`
- 功能：读取文件文本内容
- 参数：`path`, `max_chars?`
- 约束：只允许读取 task `workspace` 下路径
- 返回：文本或错误信息

## 5.2 `write`
- 功能：写文件
- 参数：`path`, `content`, `mode?`(`overwrite|append`)
- 约束：只允许写入 task `workspace` 下路径
- 返回：写入结果（字节数/路径）

## 5.3 `glob`
- 功能：按模式匹配文件
- 参数：`pattern`, `base_path?`
- 约束：搜索边界在 task `workspace`
- 返回：匹配路径列表（上限截断）

## 5.4 `grep`
- 功能：内容检索
- 参数：`pattern`, `path?`, `is_regex?`, `case_sensitive?`, `max_matches?`
- 约束：搜索边界在 task `workspace`
- 返回：`file:line:content` 列表（上限截断）

## 5.5 `run_bash_command`
- 功能：在任务容器内执行 bash 命令
- 参数：`command`, `timeout_seconds?`, `workdir?`
- 行为：`docker exec` 执行，返回 `exit_code/stdout/stderr`
- 备注：当前版本不做命令白名单

## 5.6 `todo`
- 功能：记录与追踪任务待办/进度
- 参数：`action`(`add|list|update|remove|clear`), `item_id?`, `content?`, `status?`
- 行为：在任务目录维护一个 `todo.json`（或同等结构）作为进度面板
- 价值：让 Agent 在长任务中可持续追踪“未做/进行中/已完成”项

## 5.7 `end`
- 功能：结束任务、打包并上传
- 参数：
  - `exclude_patterns: string[]`（必填，AI 提供黑名单）
  - `archive_name?`
  - `archive_format?`（建议 `zip|tar.gz`）
  - `summary?`
- 行为：
  1. 按黑名单打包 `workspace`
  2. 上传到 `target_type/target_id`
  3. 返回产物信息（名称、大小、hash、上传状态）
  4. 标记会话结束并触发清理

---

## 6. 打包与黑名单规则

### 6.1 黑名单来源
由 AI 调用 `end` 时传入 `exclude_patterns`。

### 6.2 黑名单匹配
- 采用 glob 风格匹配（如 `.git/**`, `.venv/**`, `node_modules/**`）。
- 黑名单仅用于“打包阶段排除”，不影响 workspace 内实际文件存在。

### 6.3 默认建议（写入 prompt，不强制）
可建议 AI 优先传：
- `.git/**`
- `.venv/**`
- `__pycache__/**`
- `.pytest_cache/**`
- `node_modules/**`
- `.mypy_cache/**`
- `.ruff_cache/**`

---

## 7. 上传到群聊/私聊设计

### 7.1 OneBot 扩展
在 `OneBotClient` 新增方法：
- `upload_group_file(group_id, file_path, name?)`
- `upload_private_file(user_id, file_path, name?)`

通过 `_call_api` 调用对应动作（具体动作名按当前 OneBot 实现适配）。

### 7.2 上传流程
`end` 根据 `target_type` 分发：
- `group` -> 上传群文件
- `private` -> 上传私聊文件

### 7.3 失败回退
如遇实现不支持上传动作：
- 尝试文件消息段回退（视协议实现）；
- 若仍失败，返回明确错误并保留本地产物路径用于人工处理。

### 7.4 LLM 连续失败通知
- 对“单次 LLM 请求”设置最大重试次数 5（不是全任务累计失败次数）。
- 若该次请求连续 5 次失败，立即向 `target_type/target_id` 发送失败通知。
- 通知内容至少包含：任务 ID、失败阶段、错误摘要、建议重试信息。
- 发送通知后结束任务并执行清理流程，避免进入无效重试循环。

---

## 8. 配置项计划（`config.toml.example`）

新增段：`[code_delivery]`

建议字段：
- `enabled = true`
- `task_root = "data/code_delivery"`
- `docker_image = "ubuntu:24.04"`
- `container_name_prefix = "code_delivery_"`
- `container_name_suffix = "_runner"`
- `default_command_timeout_seconds = 600`
- `max_command_output_chars = 20000`
- `default_archive_format = "zip"`
- `max_archive_size_mb = 200`
- `cleanup_on_finish = true`
- `cleanup_on_start = true`
- `llm_max_retries_per_request = 5`
- `notify_on_llm_failure = true`

并在 `src/Undefined/config/loader.py` 的 `Config` 中新增对应字段与解析。

---

## 9. 代码落点计划

### 9.1 新增 agent
`src/Undefined/skills/agents/code_delivery_agent/`
- `config.json`
- `intro.md`
- `prompt.md`
- `handler.py`
- `tools/`

### 9.2 工具子目录
- `tools/read/{config.json,handler.py}`
- `tools/write/{config.json,handler.py}`
- `tools/glob/{config.json,handler.py}`
- `tools/grep/{config.json,handler.py}`
- `tools/run_bash_command/{config.json,handler.py}`
- `tools/todo/{config.json,handler.py}`
- `tools/end/{config.json,handler.py}`

### 9.3 需修改文件
- `src/Undefined/onebot.py`（文件上传 API）
- `src/Undefined/config/loader.py`（配置解析）
- `config.toml.example`（示例配置）
- `README.md`（补充 code delivery agent 的使用说明）
- `src/Undefined/skills/README.md`（补充新增 agent/tool 说明）
- `src/Undefined/skills/agents/README.md`（补充 code_delivery_agent 结构与约束）

### 9.4 新增 TODO 文档
- `src/Undefined/skills/agents/code_delivery_agent/TODO.md`
- 用于列“后续可扩展工具”和技术债。

---

## 10. TODO（后续可扩展工具清单）

以下先记录，不纳入当前最小版本：
- `list_directory`：快速列目录树
- `read_many`：批量读取文件减少轮次
- `replace_in_file`：结构化替换
- `download_to_workspace`：显式下载远程依赖
- `inspect_env`：查看容器内工具链版本
- `checkpoint`：阶段性产物留档
- `restore_checkpoint`：失败回滚
- `artifact_list`：列当前任务已产物

---

## 11. 验收计划

### 11.1 基本用例
1. `source_type=empty`：创建代码、执行命令、`end` 打包上传成功。
2. `source_type=git`：clone 仓库、修改代码、执行命令、`end` 上传成功。
3. `todo` 工具可正常新增/列出/更新/删除待办并持久化。
4. `source_type=empty` 时最终产物包含有效 `README.md`。
5. 任务结束前已补全必要文档（至少含运行方式与使用说明）。

### 11.2 黑名单验证
- 传入 `.git/**`, `.venv/**` 后，包内不包含对应目录。

### 11.3 清理验证
- 成功路径：任务结束后容器不存在，`data/code_delivery/{task_uuid}` 被清理。
- 异常路径：中途报错后也会触发兜底清理。
- 启动路径：每次 agent 启动前会清理 `data/code_delivery/` 下历史目录和匹配前后缀规则的残留 Docker 容器。

### 11.4 上传验证
- 群聊上传成功。
- 私聊上传成功。
- 上传失败时返回明确可排查信息。

### 11.5 LLM 失败通知验证
- 人为制造 LLM 请求连续失败场景。
- 单次请求连续失败达到 5 次后，目标群/私聊能收到失败通知与失败原因。
- 通知后任务终止并完成容器与 workspace 清理。

### 11.6 文档完善验证
- 功能实现后，仓库文档已同步更新（`README.md`、`src/Undefined/skills/README.md`、`src/Undefined/skills/agents/README.md`）。
- `source_type=empty` 产物中的 `README.md` 内容完整且可指导运行。

---

## 12. 风险与注意事项

1. 当前不做命令白名单，执行能力较强，需明确仅在可信场景下使用。
2. 当前全程开网，任务可能访问外部网络，需在部署侧做好总控审计。
3. OneBot 各实现上传文件 API 兼容性差异较大，需要做动作名适配和回退。
4. Ubuntu 基础镜像默认工具较少，若业务常用 `git/zip/tar`，需要在容器准备阶段自动安装或改用预构建镜像。

---

## 13. 分阶段实施顺序

### Phase 1（基础链路）
- 建 agent 骨架 + 7 工具框架（含 `todo`）
- 启动前残留清理（`data/code_delivery/*` + 命名匹配容器）
- 容器前后缀命名机制
- 容器创建/exec/销毁
- workspace/task_uuid 生命周期

### Phase 2（交付闭环）
- `end` 打包实现（含黑名单）
- OneBot 文件上传接口
- 成功后自动清理
- 文档补全约束落地（空仓必须有 README）

### Phase 3（配置与稳定性）
- `config.toml.example` + `Config` 解析
- LLM 单次请求连续失败 5 次通知机制
- 日志增强、异常路径补全
- 仓库文档完善与同步
- 回归测试与验收

---

## 14. 当前状态说明

本文件为“持久化实施计划”，用于后续开发执行。
当前未开始修改功能代码。
