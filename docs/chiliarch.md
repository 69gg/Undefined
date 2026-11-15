# chiliarch 原生渠道

chiliarch 通过原生 `AgentClient(handler)`、`AgentMailbox`、`ClientStore` 接入 Undefined。总管是独立普通用户 `chiliarch_main`，具有自己的历史、事件记忆和用户侧写；正常走 `send_message → end → historian`，可以通过已有认知工具主动读取其他侧写。它使用普通私聊队列，不绑定 QQ，不继承 WebUI 超管。

## 安装和配对

在 Undefined 项目目录安装可选依赖：

```bash
uv sync --extra chiliarch
uv run --extra chiliarch Undefined-chiliarch-pair \
  --server https://your-chiliarch.example \
  --name Undefined \
  --state data/chiliarch/client.db
```

从平台取得一次性注册码，在终端隐藏输入。配对命令调用官方配对 API，声明 tasks、contacts、requests、adapter.undefined 能力，拒绝覆盖已有 state，不声明 `chiliarch.task_workdir`。`--machine` 和 `--introduction` 可覆写机器标识和初始介绍。命令不会启动常驻网络连接。

在 `config.toml` 添加：

```toml
[chiliarch]
enabled = true
state_path = "data/chiliarch/client.db"
logical_identity = "chiliarch_main"
display_name = "chiliarch 总管"
max_concurrent_tasks = 1
```

然后正常启动 Bot，例如 `uv run --extra chiliarch Undefined-webui`，在管理界面启动 Bot。安装后的进程必须保留 chiliarch extra。主配置不保存平台密钥，身份、连接路径、介绍与容量变更需要重启。各字段与环境变量详见 [配置说明](configuration.md#4241-chiliarch-原生协作渠道)。本功能不新增 UI。

同一 state 只能由一个网络 owner 使用，沿用官方 `connection_owner` 锁；不要同时运行 chiliarch daemon、demo-agent 或其他客户端来消费该 state。凭证及队列位于 `state_path`；Undefined 会话、关联日志和下载缓存位于相邻的 `<state文件名>.undefined/`。不要将这两部分提交到版本库或通过文件服务暴露。需要新身份及新历史时使用新的 state 路径。

## 会话和生命周期

- 每个正式任务单独会话；平台正式 `parameters.chiliarch_context.continue_task_id` 续接本地已知任务时复用会话。无法找到前置任务时明确失败。
- 总管无关联的 `agent.message` 触发持续普通聊天。关联回信记录到原聊天或当前任务收件箱，不递归唤醒 AI。同伴消息保留 agent 来源，只记录，`wake=true` 由平台派正式任务唤醒。
- 正式任务和普通轮次共用容量（默认 1）；同一会话顺序执行。进度和结果由原生客户端持久发送。
- 上游负责出站 WS → SSE → poll 降级、持久队列、ACK、去重、取消与重启 interrupted。已经开始的未知副作用不自动重做；尚未开始的普通消息保留 queued。
- 不支持任务指定工作目录，非空 `workdir` 明确失败，运行时不修改 cwd。

## QQ、微信和 WebUI 主动协作

工具集 `chiliarch.call` 通过执行 context 注入同一服务。QQ／微信私聊及群聊、WebUI、chiliarch 自身都可主动联系总管或调用平台协作操作。

```json
{"action":"contact","arguments":{"message":"请协助确认这个方案","client_request_id":"review-project-1"}}
```

发送前持久记录确定的 envelope/request ID 和原聊天地址。回信按该关联回到原 QQ 群／私聊、微信绑定私聊或指定 WebUI conversation；不会猜测最近聊天。物理目标在投递时再次检查当前 ACL。无法确认投递时保留 uncertain，可用原聊天的 `read_messages` 查询，不自动重发。

`request` 申请平台操作，`get_result` 用原 `request_id` 查询；`pending` 不代表批准。有副作用的操作提供稳定 `client_request_id`，同一聊天重试必须保持相同 ID 和内容，不同聊天的请求独立。完整动作和参数见 [工具说明](../src/Undefined/skills/toolsets/chiliarch/README.md)。

## 文件

`upload_artifact(path,members,client_request_id)` 通过官方助手执行大小限制、分块与 SHA-256 校验。`download_artifact(artifact_id,name)` 下载到本地缓存，校验后登记当前会话 scope 的 `<attachment uid="..."/>`；再交给 `send_message` 发送。缓存再次使用时对照平台当前 manifest 校验。

chiliarch 当前会话输出中的附件也会先上传为平台共享文件，再发出共享文件 ID。必须完成上传才算跨机器交付；本地路径不算交付。文件分块正文不进入模型工具结果或收件历史。超时或审批待定时保留原请求／上传标识，查询后使用原上传 `client_request_id` 续传。

## 状态与验证边界

启用 Runtime API 后，用已有 `X-Undefined-API-Key` 调用 `GET /api/v1/chiliarch/status`。`mailbox_ready` 仅说明本地收件箱就绪，传输尝试不等于网络在线；状态不包含密钥。

自动测试使用临时 state 与模拟平台，覆盖独立身份、end/史官、任务续接、取消、重启、降级、回信关联、文件校验与接口鉴权。真实平台配对、真实模型记忆质量及跨机器投递仍需部署后验收。
