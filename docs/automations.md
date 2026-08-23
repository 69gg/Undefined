# 自动化工作流（Automations）

自动化让你用一张可视化流程图描述「**满足什么条件时，机器人自动做什么**」：消息命中关键词或 @、有人拍一拍、成员进退群、到达设定时间，都会按图中节点依次执行工具调用、模板加工、LLM 生成与条件分支，还能直接接管本轮 AI 回复。

每张图由三部分组成：

- **触发器（start）**：什么时候运行；
- **节点**：每一步做什么（调用工具、整理文本、生成内容、判断分支、循环）；
- **连线（edges）**：节点之间的先后顺序。

能力边界：自动化不提供 HTTP 请求节点、代码执行节点、人工审批和独立子工作流文件；需要更复杂的外部调用时，请封装成工具后在工作流里使用。

## 典型用途

| 场景 | 推荐做法 |
|---|---|
| 定时提醒 / 每日播报 | `cron` / `daily` 触发 + 一个 LLM 或模板节点 |
| 关键词 / @ 应答 | `message` 触发，配置 `mentions` 与文本匹配，需要时开启「接管本轮 AI 回复」 |
| 入群欢迎 / 退群提示 | `member_join` / `member_leave` 触发，`{{trigger.nickname}}` 直接可用 |
| 拍一拍彩蛋 | `poke` 触发 |
| 多步骤任务链 | 多个节点串成一条线，中间用变量传递结果 |

## 三种创建方式

1. **对话创建**：直接告诉 AI 要什么，例如「每天早上八点半给我发一条待办提醒」，AI 会调用 `automation.create` 帮你建好。
2. **WebUI 画布编辑器**：在「自动化」页新建或编辑，从节点盘添加节点、点选出点和目标完成连线，在右侧检查器填写参数。详见 [WebUI 指南](webui-guide.md)。
3. **API 调用**：通过 Runtime API 的 `/api/v1/automations` 系列端点增删改查，字段说明见 [OpenAPI 说明](openapi.md)。

管理入口统一为六个工具 / API 动作：`automation.list` / `get` / `create` / `update` / `delete` / `set_enabled`。除了画完整流程图（提交 `nodes` + `edges`），简单场景还可以用「短命令」写法——只声明触发条件加一个动作（一段 prompt、一个工具或一个 Agent）。

## 触发器（start）

每张图有且只有一个 `start` 节点。消息类触发必须选择生效场景 `channels`（可多选）：`group`（QQ 群聊）、`private`（QQ 私聊）、`wechat`（微信私聊），并可用 `group_ids` / `user_ids` 进一步收窄。时间类触发不看场景，发送目标由任务的 `address` 决定（如 `qq:<QQ号>`、`group:<群号>`、`wechat:<逻辑QQ号>`）。

| kind | 含义 | 备注 |
|---|---|---|
| `message` | 群聊 / 私聊 / 微信消息 | 需选 `channels` |
| `poke` | 拍一拍 | 仅群聊、QQ 私聊 |
| `member_join` / `member_leave` | 入群 / 退群 | 仅群聊 |
| `cron` | 五段 crontab 定时 | 如 `0 9 * * *` |
| `daily` | 每天固定时刻 | 补零的 `HH:MM`（`00:00`–`23:59`） |
| `at` | 单次定时 | ISO-8601 日期时间，时区可选 |
| `interval` | 固定间隔循环 | 正整数秒 |

时间格式在保存时即校验，非法配置会直接报错，不会出现「保存成功却从不执行」的情况。

### @ 匹配规则（仅 message）

消息里的 at 在匹配前形如 `[@10001]` 或 `[@10001(昵称)]`：

- `mentions: ["10001"]` 表示这条工作流要求出现 @10001，并把这一枚 @ 从文本中剥掉；`"*"` 表示消费任意一枚尚未被消费的 @；可写多条依次消费。
- 只有写入且匹配到的 @ 才会被剥除，其余 @ 原样保留在文本里。
- 不写 `mentions` 就不设 @ 条件，整段原文参与匹配。
- `pass_text` 决定下游拿到的 `{{trigger.text}}` 是原始全文（`original`）还是剥完 @ 的文本（`stripped`）；写了 `mentions` 时默认 `stripped`。
- 文本匹配支持 contains / keyword / regex 三种方式（`text_match` + `text`）。

### 是否接管本轮 AI 回复

默认情况下，命中工作流的消息仍会照常交给主 AI 回复，工作流只在后台运行。如果希望这条消息完全交给工作流处理、避免重复回复，请在 start 中显式开启「接管本轮 AI 回复」（`consume_ai_loop=true`）。WebUI 新建的任务默认既不拦截主 AI，也不自动发送最终值。

两点硬性前提：对应消息处理开关必须打开（群聊 / 私聊各自的 `should_process_*`、拍一拍的 `process_poke_message`），否则事件不会进入自动化匹配；机器人自己的消息也不会触发自动化。另外自动化逐条处理消息，发生在同 sender 消息合并之前，详见 [消息合并](message-batching.md)。

## 节点类型

| 类型 | 作用 |
|---|---|
| `tool` | 调用一个工具或 Agent，参数支持 `{{ }}` 变量 |
| `template` | 用模板整理文本，不消耗模型 |
| `llm.blank` | 自由 LLM：从工具 / 工具集 / Agent 中挑一份白名单供其调用 |
| `llm.agent` | 交给某个现成 Agent 处理 |
| `llm.main` | 走主 AI 完整流程（原「自我督办」模式） |
| `branch.if` | if / else if 条件分支，else 出边必填 |
| `branch.llm` | 由模型在若干选项中单选，选中项决定走向 |
| `loop.times` / `loop.each` | 循环执行一组子节点，次数受配置的循环上限约束（默认 25，可调大），可用 `{{index}}` / `{{item}}` |

执行规则一句话版：有依赖就等待——某节点的所有上游都完成后它才启动；无依赖的分支一旦就绪就立即并行执行。LLM 与模板节点默认只产出内容不发消息，勾选 `emit` 后才会发送（消息触发发到当前会话，时间触发发到任务地址）。任一节点失败则整图停止。

## 变量系统

- 上游输出默认可用 `{{节点id}}` 引用。
- 工具与 LLM 节点可勾选「存储为变量」（`store_output` + `output_var`），下游用 `{{名称}}` 读取；名称不能占用保留字 `trigger` / `nodes` / `index` / `item` / `vars` / `start` / `else`。
- 三种 LLM 节点还支持变量提取（`extract_vars`）：声明若干「名称 + 说明」，运行时会注入对应的 `extract_<名称>` 工具，由模型在回答时调用写入。
- 所有触发器都提供 `{{trigger.*}}`：`channel`、`sender_id`、`nickname`、`group_id`、`address`、`time` 等；普通消息额外附带当前消息的 `message_id`、`attachments`、`message_content`、`reply_context`。入退群事件的 `{{trigger.nickname}}` 会解析为新成员的群名片 / QQ 昵称。

## 从旧定时任务升级

启动时若还没有 `data/automations.json` 但存在旧的 `scheduled_tasks.json`，会自动把旧任务转换为流程图格式写入新文件；旧文件保留不动，之后也不再双写。旧 `/api/v1/schedules` 接口与 `scheduler.*` 工具已下线，统一使用 `/api/v1/automations` 与 `automation.*`。

## 配置与限制

`[automations]` 配置节控制总开关、最大节点数（30）、全局并发（16，支持热更新）、节点 / 整图超时（600s / 1200s）、循环上限（默认 25，无内置硬顶）等，完整字段见 [配置说明](configuration.md)。事件类工作流默认不设冷却时间。

停用的任务会立即取消下次执行计划，重新启用前会先做一次完整校验；校验不过的历史任务不会被删除或改写，但必须修正到合法后才能再次启用或保存编辑。
