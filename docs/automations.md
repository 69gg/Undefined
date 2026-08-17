# 条件驱动自动化（青春版工作流）

对外名称：**自动化 / Automations**。一张小图把工具、模板、LLM、if/else 与有上限的循环串起来；消息命中后可以接管本轮主 AI。

详细设计约束：不做 HTTP/代码节点、独立子工作流文件、人工审批、Console/Chat 独立编辑器。WebUI 提供画布编辑器；图数据仍是 `nodes` / `edges`。

## 存储与兼容

- 运行时只读写 `data/automations.json`
- 启动时若还没有新文件、但存在旧 `data/scheduled_tasks.json`：读取并转为 start + 节点，写入 `automations.json`；**不删除**旧文件，之后也**不双写**
- 已有 `automations.json` 时不再读取旧文件
- 运行时由 `AutomationService`（`automations/service.py`）加载图、匹配事件、跑 DAG，并用 APScheduler 触发时间类 start。工具上下文注入 `automations` 与兼容别名 `scheduler`
- 对外入口只有 `/api/v1/automations` 与 `automation.*`；不再提供 `/schedules` 或 `scheduler.*`

## 挂载点

统一在 **pipeline 之后、对应 AI loop 之前接入工作流**。`consume_ai_loop=true` 时 await 该图并拦截本轮主 AI；`false` 时后台执行、立刻放行主 AI。匹配失败仍继续后续流程。未过「是否处理消息」门控时仍做匹配旁路。Bot 自身消息不匹配。自动化看单条消息，发生在 MessageBatcher 之前。

| 入口 | 顺序 |
|---|---|
| 群聊 | `_run_pipelines` → 自动化 → `handle_auto_reply` |
| QQ 私聊 | pipeline → 自动化 → `handle_private_reply` |
| 微信私聊 | pipeline → 自动化 → `handle_private_reply`（channel=`wechat`） |
| 拍一拍 | 写历史 → 自动化 → 原 poke AI |
| 入退群 | OneBot `group_increase` / `group_decrease`，无 AI 可拦 |
| 时间 | APScheduler |

事件用当前会话上下文（`request_type` / `group_id` / `user_id` / `sender_id` / `address` / `channel` 写入工具 context）；时间触发才用 snapshot。工具节点同时注入主 AI 持有的 `cognitive_service` / `knowledge_manager` / `meme_service` / `attachment_registry`。出站走 `MessageSender`，受 `[access]` 约束。`send_message` 只填 `message` 时按该会话推断目标。

## Start：场景多选 + @ 专项

恰好一个 `id="start"`。事件类必须带 `channels`（多选，至少一项）：`group` | `private` | `wechat`。可再收窄 `group_ids` / `user_ids`。时间类不看 channels，投递仍用 `address`。

`kind`：`message` | `cron` | `daily` | `at` | `interval` | `poke` | `member_join` | `member_leave`。poke 只能 group/private；入退群只能 group。

### @ 消费规则（仅 message）

归一化入站 at 已是 `[@qq]` / `[@qq(昵称)]`。匹配时抽出 mention 列表，**按条件条款消费，而不是整段当普通字符串搜 `[@`。**

`mentions: string[]`：

- `"10001"`：必须出现该 id，并只剥这一枚 token
- `"*"`：从左到右消费一枚尚未被消费的任意 mention
- 可写多条：`["10001", "10002", "*"]`
- 空或缺省：**不做 @ 条件**，全文原样匹配、原样传入

剥除：只有写入且匹配到的 token 才删。若 token 右侧紧邻空白（半角/全角 `\u3000`/tab），空白一起删。`[@10001] 你好` → `你好`；`[@xxx]你好` 只删 token。未写入的 `@` 留在剩余文本。

然后对剩余文本做 `text_match`（contains / keyword / regex）+ `text`。

`pass_text`：`original` | `stripped`（写了 mentions 时默认 stripped，否则 original）。

下游变量：

- `{{trigger.text}}`：由 `pass_text` 决定
- `{{trigger.text_original}}` / `{{trigger.text_stripped}}`
- `{{trigger.mentions}}` / `{{trigger.mentions_all}}`
- `{{trigger.channel}}` `{{trigger.sender_id}}` `{{trigger.nickname}}` `{{trigger.address}}` `{{trigger.group_id}}` `{{trigger.time}}`

节点模板可自行选用带 @ / 不带 @ 的变量。分支 `branch.if` 用同一套 mentions 规则做 case 文本匹配，**不改**全局 `trigger.*`。

## 节点

多上游 AND join：所有入边都满足后才启动；无相互依赖的分支一旦依赖就绪就立刻并行，不等整波齐头。默认可用 `{{节点id}}` 引用上游输出。工具与三种 LLM 节点还可设置 `store_output` + `output_var`：勾选存储后，下游用 `{{名称}}`（或 `{{vars.名称}}`）读取；关掉则不写入变量。未填名称时仍按节点 ID 存储。禁止占用 `trigger` / `nodes` / `index` / `item` / `vars` / `start` / `else`。循环硬顶 **25** 次。禁止 loop 外回边。

| 类型 | 作用 |
|---|---|
| `tool` | 工具或主注册表 agent 名；args 做 `{{ }}`；可命名存储输出 |
| `template` | 无模型整形 |
| `llm.blank` | agent 模型 + 白名单 tools/toolsets/agents；可命名存储输出；可配置 `extract_vars` |
| `llm.agent` | 现成 Agent；可命名存储输出；可配置 `extract_vars` |
| `llm.main` | `AIClient.ask()`，原自我督办；可命名存储输出；可配置 `extract_vars` |
| `branch.if` | if / else if + 必填 else 出边 |
| `branch.llm` | 选项做成强制 tool `choose_<id>`，用选中 tool 走出边 |
| `loop.times` / `loop.each` | 体为子节点 id 列表；`{{index}}` / `{{item}}` |

`llm.blank` / `llm.agent` / `llm.main` 可设 `extract_vars: [{ "name", "description" }, ...]`（不含 `branch.llm`）。运行时注入 `extract_<名称>` 工具，模型调用后写入 `{{名称}}` / `{{vars.名称}}`。

LLM/template 默认不发群，`emit: true` 才发。WebUI 新建默认关闭 `consume_ai_loop` 与 `auto_send_final`。失败即停；未拦截主 AI 时工作流后台执行，主 AI 照常继续。

## 配置 `[automations]`

`enabled`、`max_nodes`（建议 30）、`max_concurrent`（默认 16）、节点超时 600s、整图超时 1200s、`blank_llm_max_iterations`（默认 100）、`loop_max_iterations`（默认与上限 25）、`default_cooldown_seconds`（事件类默认 0，不冷却）。

## 工具

`automation.list` / `get` / `create` / `update` / `delete` / `set_enabled`。短命令能表达 channels、group_ids、user_ids、mentions、text、pass_text。

WebUI「自动化」页把列表与画布做成上下两屏：上面是总数与选择，滚下去是节点盘 / 画布 / 检查器。点选卡片会滚到画布，不把列表藏掉。连线是先点出点再点目标；空白 LLM 白名单用搜索点选。工具与 LLM 检查器可勾选存储输出并填写变量名；三种 LLM 节点还可配置变量提取。图数据仍读写 `nodes` / `edges`，布局存在任务顶层 `ui`。
