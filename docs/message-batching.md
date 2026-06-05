# 同 sender 短时消息合并（Message Batcher）

> 出现场景：用户连续发送两条命令，例如先 "帮我画一只猫"、紧接着 "改成狗"。
> 老版本会触发两次 AI 调用：第一次画完猫、第二次又因 history 出现两条都画一遍，且容易回复重复。
> 启用本特性后，短窗口内同一发送者的多条消息会合并为同一轮 AI 调用，AI 一次性看到全部意图，识别"修正/补充/独立请求"自行决定如何回应。

## 设计要点

- **作用域**：按 `(scope, sender_id)` 分桶。`scope` 群聊为 `group:<gid>`，私聊为 `private:<uid>`。
- **窗口策略**：
  - `extend`（默认）：每条新消息重置定时器，并以 `max_window_seconds` 作为硬顶。
  - `fixed`：定时器从首条算起；窗口期结束统一发车。
- **硬顶**：`max_window_seconds` 防止极端情况下窗口被无限延长（`0` = 不限制，仅靠 `window_seconds` + `max_messages_per_batch` 触发发车）；`max_messages_per_batch` 达到立即发车（`0` = 不限）。
- **历史记录不变**：每条消息照旧由 `handlers/message_flow` 写入 history；batcher 只决定何时调用 AI。
- **拍一拍永远旁路**：拍一拍触发不进入 batcher，直接立即处理。
- **群聊 @bot 规则**：
  - 当前桶**为空**且新消息 @bot → 进入 buffer，本批走 `add_group_mention_request`（提及优先级）。
  - 当前桶**非空**且新消息 @bot → 不打断现有 buffer，**单独立即处理**这条 @bot 消息。
- **关停**：`MessageBatcher.flush_all()` 在进程退出前 flush 所有未发车的桶，并进入 shutdown 模式；之后新消息不再进入缓冲桶，而是立即直送，避免关停期间出现无限等待或漏桶。`MessageHandler.close()` 会在停止队列前等待队列 drain 完成。

## Prompt 行为

合并时构造的 `<message>` 块按时间先后排列；当 `count >= 2` 时追加"连续消息说明"：

> 把整批 `<message>` 视作本轮的全部输入：
> 0. 这些 `<message>` 共同构成"当前输入批次"，同批前几条不是历史旧任务；批次之外的历史消息仍只作为背景，不能回溯拾荒。
> 1. 区分每条意图：【独立请求】各自回应不要遗漏（与平时一样，可多次 send_message 自然分发）；【修正/否定/补充/打断】则以最后一次明确意图为准，旧的不再执行。
> 2. 拿不准时偏向"独立请求"，宁多勿漏。
> 3. 整批在本轮一次性处理完，不要为同一意图重复输出。

`res/prompts/undefined.xml`、`res/prompts/undefined_nagaagent.xml` 与 `res/IMPORTANT/each.md` 均按"当前输入批次"适配：有【连续消息说明】时整批当前 `<message>` 都属于本轮输入；没有连续说明时，当前输入批次退化为最后一条消息。防幽灵任务规则仍然生效，但它只隔离当前输入批次之外的历史消息；「催促/在吗」不等于新任务，历史同类或语义等价操作不得自动重跑（与 each.md 硬性熔断一致）。

Prompt 构建顺序按缓存命中友好设计：固定系统提示词、运行环境配置、Skills 元数据和强制规则尽量放在前面；会频繁变化的 memory / cognitive / end 摘要 / history / 当前时间 / 当前输入批次放在后面。`system_prompt_as_user=true` 时，系统块会合并进首条 user，但合并后的文本仍保留这个顺序，且当前输入批次仍在最后。

`end.memo` / `end.observations` 也按同一语义适配：当前输入批次包含多条连续消息时，短期 memo 要概括整批处理结果，认知 observations 要覆盖整批消息中有价值的新观察；这些观察不要求与 bot 相关，也不要求长期稳定，但只能来自当前输入批次。历史消息、认知记忆、侧写和最近消息参考只用于消歧，不能作为 observations 的新事实来源。后台史官收到的 `source_message` 会按时间顺序列出本批所有 `<message>`，不会只取最后一条。

> **重要**：当前主提示词按 MessageBatcher 默认开启设计。`[message_batcher].enabled = true` 是推荐和默认配置；如果关闭 batcher，连续补充/修正会退化为逐条独立 AI 调用，提示词中的"当前输入批次"语义可能不再覆盖这些连续消息，需要单独调整提示词或接受旧版逐条触发行为。

## 配置

`config.toml`：

```toml
[message_batcher]
# 总开关
enabled = true
# 等待窗口（秒），同一 sender 在窗口内的消息合并到同一轮
window_seconds = 5.0
# 策略：extend = 新消息重置窗口；fixed = 从首条算起的固定窗口
strategy = "extend"
# 硬顶：从首条算起最多等多久
max_window_seconds = 30.0
# 单批最多条数（0 = 不限）；达到立即发车
max_messages_per_batch = 0
# 群聊是否启用合并
group_enabled = true
# 私聊是否启用合并
private_enabled = true
# 命中斜杠命令时是否先 flush 当前 sender 的 buffer（默认关闭，保持命令独立执行）
flush_on_command = false
# 投机预发送阈值（秒）。0 < pre_send_seconds < window_seconds 时启用 "speculative pre-fire"：
# 静默到该阈值就先把当前 batch 提前发给 LLM 抢时间，但 batch 仍要等到 window_seconds 才结束
pre_send_seconds = 0.0
# 投机调用已经向用户发出过任何消息后，新消息到达是否仍然取消该 inflight 调用（默认 false：不取消）
allow_cancel_after_send = false
```

支持热更新：修改后通过 WebUI 或 SIGHUP 重新加载配置即可生效，正在排队的桶会沿用新配置参数。

## 行为矩阵

| 场景 | 行为 |
|---|---|
| 群聊普通消息（无 @、无拍一拍）连续发 | 进入 batcher，窗口到期合并发车（普通队列） |
| 群聊首条 @bot | 进入 batcher，发车时走 `add_group_mention_request` |
| 群聊 buffer 已有 + 新条 @bot | 该 @bot 立即旁路单独处理；buffer 继续等待 |
| 群聊拍一拍 | 永远旁路，立即处理 |
| 私聊连续消息 | 进入 batcher，到期合并 |
| 私聊拍一拍 | 永远旁路，立即处理 |
| 超管消息 | 与普通用户一致进入 batcher，发车时走超管队列 |
| `enabled=false` | 全部旁路，行为退化为旧版 |

## 与多模型池的协作

私聊路径在发车时调用 `model_pool.select_chat_config(...)` 选模型，逻辑保持不变；合并仅影响"何时调用 AI"，不影响"用哪个模型"。

## 相关文件

- 实现：[src/Undefined/services/message_batcher/](src/Undefined/services/message_batcher/)
- 接入：[src/Undefined/services/ai_coordinator.py](src/Undefined/services/ai_coordinator.py) 中 `handle_auto_reply` / `handle_private_reply` / `_dispatch_grouped_request`
- 创建/注入：[src/Undefined/handlers/message_flow.py](src/Undefined/handlers/message_flow.py)
- 关停 flush：[src/Undefined/main.py](src/Undefined/main.py)
- 热更新：[src/Undefined/config/hot_reload.py](src/Undefined/config/hot_reload.py)
- 提示词：[res/prompts/undefined.xml](res/prompts/undefined.xml)、[res/prompts/undefined_nagaagent.xml](res/prompts/undefined_nagaagent.xml)
- 测试：[tests/test_message_batcher.py](tests/test_message_batcher.py)

## 投机预发送（Speculative Pre-fire）

> 目标：当用户处于"打字停顿"状态时，让 LLM 抢先开始处理，而不必等到完整的 `window_seconds` 静默才开始。

### 双计时器状态机

每个 `(scope, sender_id)` 桶维护两条独立的"静默计时器"：

- **T1 = `window_seconds`** —— 打字静默阈值，决定 batch 何时结束。
- **T2 = `pre_send_seconds`** —— 投机预发送阈值，要求严格 `0 < T2 < T1`。
  达到 T2 时把当前 batch 提前发给 LLM（"speculative pre-fire"），但 batch **不结束**，T1 才正式结束。

桶状态：

| Phase | 含义 |
|---|---|
| `TYPING` | 等待 T1/T2 静默 |
| `SPECULATING` | T2 已触发，请求已入队或 inflight LLM 在跑；T1 仍未到 |
| `FINALIZING` | T1 已到，等 inflight（若有）自然结束 |

### 新消息到来时的决策

- **TYPING**：append 到 items，重置 T1/T2。
- **SPECULATING**：
  - 检查 inflight 是否已经向用户发出过任何消息（来自 `RequestContext.get_resource("message_sent_this_turn")`）。
  - inflight **尚未发消息** → 调 `inflight_task.cancel()`，桶回到 `TYPING`，新消息追加进去，重置 T1/T2；inflight 协程在 `RequestContext` 里清理后退出，**不写入回复历史**。
  - T2 已经把请求入队但 coordinator 还没注册 inflight → 取消旧 `BatchDispatchToken`；旧请求即使稍后被队列取出，也会在 `execute_reply` 入口跳过，新消息继续合并进重新计时的 batch。
  - inflight **已经发过消息** 且 `allow_cancel_after_send=False`（默认安全） → 不取消 inflight，**新消息开新 batch**（旧桶在 inflight 自然结束后清理）。
- **FINALIZING**：旧 batch 已到 T1，若此时又来新消息，直接开新桶，不阻塞旧 inflight 收尾。
- `allow_cancel_after_send=True` 会在 inflight 已发过消息后仍取消，可能造成半截回复、重复回复或上下文撕裂，仅极端场景启用。

### 防竞态设计

- 所有桶状态变更在 `MessageBatcher._lock` 内完成；LLM/队列等待不会发生在锁内。
- timer 触发后由 `asyncio.create_task` 创建 flush 协程，强引用挂到 `_pending_tasks: set[Task]`，`task.add_done_callback(self._pending_tasks.discard)` 清理（asyncio 文档要求避免被 GC）。
- T2 预发送会给队列请求附带 `BatchDispatchToken`。新消息抢占时先取消旧 token；若旧请求已入队但尚未执行，`AICoordinator.execute_reply()` 会直接跳过，避免队列拥堵窗口里的陈旧回复。
- T2 的 `flush_callback` 若异常或被取消，桶会从 `SPECULATING` 回滚到 `TYPING` 并换新 token，保留原 items 等 T1 正常重试，避免静默丢消息。
- T1 到期时如果 batch 已经被 T2 投机发出，只负责结束 bucket/等待已知 inflight，不会再次调用 `flush_callback`，避免同一批消息重复入队。
- `unregister_inflight(scope, sender_id, task)` 必须携带 task 身份并校验；旧任务的 `finally` 不会误清理新一轮已注册的 inflight。
- `flush_all()` 在关停时设置 shutdown 标记，循环遍历所有桶执行等价 T1 路径，并 `await` 所有未完成的 flush task；若收尾过程中又出现新桶，会继续清空直到没有 pending bucket。shutdown 之后的新消息直接发车，不再开缓冲桶。
- `MessageHandler.close()` 的顺序是：停止自动管线热重载 → `message_batcher.flush_all()` → `queue_manager.drain()` 等待已入队/在途回复自然收敛 → `queue_manager.stop()` → flush 历史落盘。
- coordinator 在 `execute_reply` 入口调用 `register_inflight(scope, sender_id, task, ctx)`，在 `finally` 调 `unregister_inflight(...)`；`asyncio.CancelledError` 被识别为 "投机抢占"，仅记录信息日志且不重试。

### 兼容回退

`pre_send_seconds <= 0` 或 `>= window_seconds` 时投机模式自动关闭，行为退化为旧版"T1 静默到期才发车"。`enabled=false` 时整体退化为逐条触发。
