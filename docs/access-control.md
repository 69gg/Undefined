# 访问控制配置说明

本文档说明 `config.toml` 中 `[access]` 的访问控制能力，包括模式开关、群/私聊黑白名单，以及 superadmin 的私聊绕过策略。

## 配置项

```toml
[access]
mode = "off" # off / blacklist / allowlist

allowed_group_ids = []
blocked_group_ids = []

allowed_private_ids = []
blocked_private_ids = []

superadmin_bypass_allowlist = true
superadmin_bypass_private_blacklist = false
```

## mode 行为

| mode | 行为 |
| --- | --- |
| `off` | 关闭访问控制；不按黑白名单拦截 |
| `blacklist` | 仅按黑名单拦截：`blocked_group_ids` / `blocked_private_ids` |
| `allowlist` | 仅按白名单放行：`allowed_group_ids` / `allowed_private_ids` |

说明：
- `mode=blacklist` 时，`allowed_*` 不参与判定。
- `mode=allowlist` 时，`blocked_*` 不参与判定。
- `mode=allowlist` 时，群/私聊按各自列表独立生效：
  - `allowed_group_ids=[]` 表示群聊不限制。
  - `allowed_private_ids=[]` 表示私聊不限制。
- 若 `mode` 未配置且已有黑/白名单字段，系统会进入兼容模式（legacy）以保持旧版本行为。建议尽快显式设置 `mode`。

## superadmin 私聊绕过

仅影响私聊判定，不影响群聊判定：

- `superadmin_bypass_allowlist=true`  
  在 `mode=allowlist` 时，superadmin 可绕过 `allowed_private_ids`。
- `superadmin_bypass_private_blacklist=true`  
  在 `mode=blacklist` 时，superadmin 可绕过 `blocked_private_ids`。

## 常见示例

### 1) 关闭访问控制

```toml
[access]
mode = "off"
```

### 2) 黑名单模式（屏蔽指定群和私聊）

```toml
[access]
mode = "blacklist"
blocked_group_ids = [123456789, 987654321]
blocked_private_ids = [1122334455]
superadmin_bypass_private_blacklist = false
```

### 3) 白名单模式（只放行指定群和私聊）

```toml
[access]
mode = "allowlist"
allowed_group_ids = [123456789, 987654321]
allowed_private_ids = [1122334455]
superadmin_bypass_allowlist = true
```

## 适用范围

访问控制同时作用于：
- 入站消息处理（群聊、私聊、拍一拍）
- 出站消息发送（文本、文件、拍一拍）
- 工具调用和定时任务发送链路

因此，配置可统一约束“收消息”和“发消息”。
