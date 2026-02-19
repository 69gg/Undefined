# 多模型池功能

## 功能概述

- **Chat 模型池（私聊）**：轮询/随机自动切换，或在私聊中通过「选X」指定模型
- **Agent 模型池**：按策略（轮询/随机）自动分配，无需用户干预

> 仅私聊支持用户手动切换 Chat 模型；群聊始终使用主模型。

## 配置方式

### 方式一：WebUI

启动 `uv run Undefined-webui`，登录后进入「配置修改」页：

- **全局开关**：`features` → `pool_enabled` 设为 `true`
- **Chat 模型池**：`models` → `chat` → `pool`，设置 `enabled`、`strategy`，在 `models` 列表中添加/移除条目
- **Agent 模型池**：`models` → `agent` → `pool`，同上

每次修改自动保存并热更新，无需重启。

### 方式二：直接编辑 config.toml

## 配置

### 1. 全局开关

```toml
[features]
pool_enabled = true  # 默认 false，需显式开启
```

### 2. Chat 模型池

```toml
[models.chat.pool]
enabled = true
strategy = "round_robin"  # "default" | "round_robin" | "random"

[[models.chat.pool.models]]
model_name = "claude-sonnet-4-20250514"
api_url = "https://api.anthropic.com/v1"
api_key = "sk-ant-xxx"
# 其他字段（max_tokens, thinking_* 等）可选，缺省继承主模型

[[models.chat.pool.models]]
model_name = "deepseek-chat"
api_url = "https://api.deepseek.com/v1"
api_key = "sk-ds-xxx"
```

### 3. Agent 模型池

```toml
[models.agent.pool]
enabled = true
strategy = "round_robin"  # "default" | "round_robin" | "random"

[[models.agent.pool.models]]
model_name = "claude-sonnet-4-20250514"
api_url = "https://api.anthropic.com/v1"
api_key = "sk-ant-xxx"
```

### strategy 说明

| 值 | 行为 |
|----|------|
| `default` | 只使用主模型，忽略池中模型 |
| `round_robin` | 按顺序轮流使用池中模型 |
| `random` | 每次随机选择池中模型 |

> `pool.models` 中只有 `model_name` 必填，其余字段缺省时继承主模型配置。

## 私聊使用方法

### 自动轮换

配置 `strategy = "round_robin"` 或 `"random"` 后，私聊请求会自动在池中模型间切换，无需任何操作。

### 手动指定模型（私聊）

1. 私聊发送 `/compare <问题>` 或 `/pk <问题>`，bot 并发请求所有模型并编号返回：

```
你: /compare 写一首关于春天的诗

bot:
正在向 3 个模型发送问题，请稍候...

问题: 写一首关于春天的诗

【1】gpt-4o
春风拂面暖如酥...

【2】claude-sonnet-4-20250514
春日融融暖意浓...

【3】deepseek-chat
春回大地万象新...

回复「选X」可切换到该模型并继续对话
```

2. 5 分钟内回复 `选2`，后续私聊固定使用第 2 个模型继续对话。

3. 偏好持久化保存在 `data/model_preferences.json`，重启后保留。

## 开关层级

```
features.pool_enabled        ← 全局总开关（false 时完全不生效）
  └─ models.chat.pool.enabled   ← Chat 模型池开关
  └─ models.agent.pool.enabled  ← Agent 模型池开关
```

## 注意事项

- 不同模型使用独立队列，互不影响
- 所有模型的 Token 使用均会被统计
- 「选X」状态 5 分钟后过期
- 群聊不受多模型池影响，始终使用主模型

## 代码结构

| 文件 | 职责 |
|------|------|
| `config/models.py` | `ModelPool`, `ModelPoolEntry` 数据类 |
| `config/loader.py` | 解析 pool 配置，字段缺省继承主模型 |
| `ai/model_selector.py` | 纯选择逻辑：策略、偏好存储、compare 状态 |
| `services/model_pool.py` | 私聊交互服务：`/compare`、「选X」、`select_chat_config` |
| `services/ai_coordinator.py` | 持有 `ModelPoolService`，私聊队列投递时选模型 |
| `handlers.py` | 私聊消息委托给 `model_pool.handle_private_message()` |
| `skills/agents/runner.py` | Agent 执行时调用 `model_selector.select_agent_config()` |
| `utils/queue_intervals.py` | 注册 pool 模型的队列间隔 |
