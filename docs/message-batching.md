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
- **历史记录不变**：每条消息照旧由 `handlers.py` 写入 history；batcher 只决定何时调用 AI。
- **拍一拍永远旁路**：拍一拍触发不进入 batcher，直接立即处理。
- **群聊 @bot 规则**：
  - 当前桶**为空**且新消息 @bot → 进入 buffer，本批走 `add_group_mention_request`（提及优先级）。
  - 当前桶**非空**且新消息 @bot → 不打断现有 buffer，**单独立即处理**这条 @bot 消息。
- **关停**：`MessageBatcher.flush_all()` 在进程退出前 flush 所有未发车的桶，避免丢消息。

## Prompt 行为

合并时构造的 `<message>` 块按时间先后排列；当 `count >= 2` 时追加"连续消息说明"：

> 把整批 `<message>` 视作本轮的全部输入：
> 1. 区分每条意图：【独立请求】各自回应不要遗漏（与平时一样，可多次 send_message 自然分发）；【修正/否定/补充/打断】则以最后一次明确意图为准，旧的不再执行。
> 2. 拿不准时偏向"独立请求"，宁多勿漏。
> 3. 整批在本轮一次性处理完，不要为同一意图重复输出。

`res/prompts/undefined.xml` 与 `res/prompts/undefined_nagaagent.xml` 的 `trigger id="4"` 也已同步更新为相同语义。

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
# 命中斜杠命令时是否 flush 当前 sender 的 buffer（保留字段，当前未消费）
flush_on_command = true
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

- 实现：[src/Undefined/services/message_batcher.py](src/Undefined/services/message_batcher.py)
- 接入：[src/Undefined/services/ai_coordinator.py](src/Undefined/services/ai_coordinator.py) 中 `handle_auto_reply` / `handle_private_reply` / `_dispatch_grouped_request`
- 创建/注入：[src/Undefined/handlers.py](src/Undefined/handlers.py)
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
  - inflight **已经发过消息** 且 `allow_cancel_after_send=True` → 仍取消，可能造成重复发送，仅极端场景启用。

### 防竞态设计

- 所有桶状态变更在 `MessageBatcher._lock` 内完成；LLM/队列等待不会发生在锁内。
- timer 触发后由 `asyncio.create_task` 创建 flush 协程，强引用挂到 `_pending_tasks: set[Task]`，`task.add_done_callback(self._pending_tasks.discard)` 清理（asyncio 文档要求避免被 GC）。
- T2 预发送会给队列请求附带 `BatchDispatchToken`。新消息抢占时先取消旧 token；若旧请求已入队但尚未执行，`AICoordinator.execute_reply()` 会直接跳过，避免队列拥堵窗口里的陈旧回复。
- T1 到期时如果 batch 已经被 T2 投机发出，只负责结束 bucket/等待已知 inflight，不会再次调用 `flush_callback`，避免同一批消息重复入队。
- `unregister_inflight(scope, sender_id, task)` 会校验 task 身份；旧任务的 `finally` 不会误清理新一轮已注册的 inflight。
- `flush_all()` 在关停时遍历所有桶执行等价 T1 路径，并 `await` 所有未完成的 flush task。
- coordinator 在 `execute_reply` 入口调用 `register_inflight(scope, sender_id, task, ctx)`，在 `finally` 调 `unregister_inflight(...)`；`asyncio.CancelledError` 被识别为 "投机抢占"，仅记录信息日志且不重试。

### 兼容回退

`pre_send_seconds <= 0` 或 `>= window_seconds` 时投机模式自动关闭，行为退化为旧版"T1 静默到期才发车"。`enabled=false` 时整体退化为逐条触发。
