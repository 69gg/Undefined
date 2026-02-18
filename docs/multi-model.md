# 多模型池功能

## 功能概述

多模型池功能允许你配置多个 AI 模型，并通过以下方式使用：

- **轮询/随机选择**：自动在多个模型间轮换或随机选择
- **用户指定模型**：通过命令切换到特定模型
- **多模型比较**：同一问题并发发给所有模型，比较结果后选择最佳分支继续对话

## 配置方法

### 1. 全局开关

在 `config.toml` 中启用多模型功能（默认关闭，需显式开启）：

```toml
[models]
pool_enabled = true  # 全局开关（默认 false），设为 true 启用多模型功能
```

### 2. Chat 模型池配置

```toml
[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o"
max_tokens = 8192

# 模型池配置
[models.chat.pool]
enabled = true  # Chat 模型池开关
strategy = "default"  # 选择策略："default" | "round_robin" | "random"

# 额外模型列表
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

### 3. Agent 模型池配置

```toml
[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-xxx"
model_name = "gpt-4o-mini"
max_tokens = 4096

[models.agent.pool]
enabled = true
strategy = "default"

[[models.agent.pool.models]]
model_name = "claude-sonnet-4-20250514"
api_url = "https://api.anthropic.com/v1"
api_key = "sk-ant-xxx"
```

### 配置说明

- **enabled**：模型池开关，关闭后使用主模型
- **strategy**：
  - `default`：只使用主模型（不使用池中模型）
  - `round_robin`：轮询池中模型
  - `random`：随机选择池中模型
- **字段缺省**：pool.models 中的每个条目，只有 `model_name` 是必填的，其余字段缺省时继承主模型配置

## 使用方法

### 1. 查看可用模型

```
@bot /model
```

输出示例：
```
当前模型: gpt-4o
主模型: gpt-4o
策略: default
可用模型:
  1. claude-sonnet-4-20250514
  2. deepseek-chat
用法: /model <模型名|序号> 切换, /model reset 恢复默认
```

### 2. 切换模型

```
@bot /model 1
@bot /model claude-sonnet-4-20250514
```

切换后，该用户在该群的后续对话将使用指定模型。

### 3. 恢复默认模型

```
@bot /model reset
```

### 4. 多模型比较

```
@bot /compare 写一首关于春天的诗
```

或使用别名：
```
@bot /pk 什么是量子计算
```

输出示例：
```
问题: 写一首关于春天的诗

【1】gpt-4o
春风拂面暖如酥，
万物复苏绿满途。
...

【2】claude-sonnet-4-20250514
春日融融暖意浓，
百花争艳竞芳容。
...

【3】deepseek-chat
春回大地万象新，
柳绿花红醉煞人。
...

回复「选2」可切换到该模型
```

### 5. 选择比较结果

在比较结果后 5 分钟内，回复：
```
选2
```

系统会自动切换到第 2 个模型（claude-sonnet-4-20250514），后续对话使用该模型。

## 偏好存储

- **存储范围**：按群+按用户存储，每个群里每个用户可以有自己的模型偏好
- **私聊支持**：私聊按用户存储
- **持久化**：偏好保存在 `data/model_preferences.json`，重启后保留

## 开关层级

多模型功能有三层开关：

1. **全局开关** (`models.pool_enabled`)：关闭后所有多模型功能禁用
2. **Chat 模型池开关** (`models.chat.pool.enabled`)：控制 Chat 模型池
3. **Agent 模型池开关** (`models.agent.pool.enabled`)：控制 Agent 模型池

只有全局开关开启，且对应的模型池开关开启，该模型池才会生效。

## WebUI 兼容性

多模型功能完全兼容 WebUI，配置通过 WebUI 编辑后会自动生效（支持热更新）。

## 注意事项

1. **API Key 安全**：不要将 `config.toml` 提交到版本控制系统
2. **队列隔离**：不同模型使用独立的队列，互不影响
3. **Token 统计**：所有模型的 Token 使用都会被统计
4. **比较超时**：比较功能会并发请求所有模型，如果某个模型响应慢，会影响整体速度
5. **选择过期**：比较结果的选择状态 5 分钟后过期

## 常见问题

### Q: 如何禁用多模型功能？

A: 在 `config.toml` 中设置：
```toml
[models]
pool_enabled = false
```

### Q: 可以只为 Chat 启用多模型，Agent 不启用吗？

A: 可以，分别控制：
```toml
[models]
pool_enabled = true

[models.chat.pool]
enabled = true

[models.agent.pool]
enabled = false
```

### Q: 轮询策略是如何工作的？

A: `round_robin` 策略会按顺序轮流使用池中的模型（不包括主模型）。每次请求使用下一个模型。

### Q: 用户偏好会影响其他用户吗？

A: 不会。每个用户在每个群的偏好是独立的，互不影响。

### Q: 比较功能支持工具调用吗？

A: 不支持。比较功能只进行纯文本生成，不调用工具，以确保结果的可比性。
