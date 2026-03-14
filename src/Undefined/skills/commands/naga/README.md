# /naga 命令说明

## 这是什么？

NagaAgent 是一个可以接入 Undefined 的外部 AI 助手。
通过 `/naga` 命令，你可以把自己的 NagaAgent 绑定到 QQ 群，绑定之后，NagaAgent 里的特定功能就可以向你发送消息。

## 普通用户

普通用户只需要用到一个子命令：`bind`（绑定）。

### 如何绑定？

1. 在**群聊**中发送：`/naga bind <你的naga_id>`
2. 系统会提示"申请已提交，等待超管审核"
3. 超级管理员审核通过后，你会收到私聊通知
4. 绑定完成！你的 NagaAgent 即可开始使用

### 注意事项

- `naga_id` 是你在 NagaAgent 中设置的标识，不是 QQ 号
- 每个 `naga_id` 只能绑定一次，不能重复申请
- 如果已在审核队列中，无需重复提交

## 管理员命令（仅超级管理员）

以下命令仅超级管理员可使用，用于管理所有绑定：

| 子命令 | 用法 | 说明 |
|--------|------|------|
| approve | `/naga approve <naga_id>` | 通过绑定申请，系统会自动生成 Token 并通知申请人 |
| reject | `/naga reject <naga_id>` | 拒绝绑定申请，申请人会收到私聊通知 |
| revoke | `/naga revoke <naga_id>` | 吊销已有绑定，该 NagaAgent 将无法继续使用 |
| list | `/naga list` | 查看所有活跃的绑定（含使用次数） |
| pending | `/naga pending` | 查看等待审核的申请列表 |
| info | `/naga info <naga_id>` | 查看指定绑定的详细信息（Token、使用次数、创建时间等） |

## 完整示例

```
# 普通用户：在群聊中提交绑定申请
/naga bind my-naga-001

# 超级管理员：查看待审核列表
/naga pending

# 超级管理员：通过申请
/naga approve my-naga-001

# 超级管理员：查看绑定详情
/naga info my-naga-001

# 超级管理员：吊销绑定
/naga revoke my-naga-001
```

## 常见问题

**Q: 提示"Naga 集成未启用"？**
A: 请联系管理员开启相关配置开关。

**Q: 在群里发了 /naga bind 没有任何反应？**
A: 该群可能不在白名单中，请联系管理员添加。

**Q: 绑定通过后 NagaAgent 怎么用？**
A: 请参考 NagaAgent 相关文档，填入QQ号以及其他几个参数即可完成对接。