# /naga 命令说明

## 这是什么？

`/naga` 用于把 QQ 用户与 NagaAgent 的远端身份绑定起来，并在需要时解除绑定。
当前只保留两个子命令：

- `/naga bind <naga_id>`
- `/naga unbind <naga_id>`

## 可见性与作用域

- `/naga` 只会在 `naga.allowed_groups` 白名单群中出现和生效
- 同时要求 `[api].enabled = true`，否则命令会整体隐藏
- 在非白名单群中，`/naga` 对用户是静默不可见的
- `/naga bind` 仅限白名单群聊
- `/naga unbind` 仅限超级管理员，可在私聊或白名单群中使用

## /naga bind

用户在白名单群中执行：

```text
/naga bind <你的_naga_id>
```

流程：

1. Undefined 本地记录一个待确认绑定，并生成唯一 `bind_uuid`
2. 请求会被发送到 Naga 端进行远端验证
3. 等待 Naga 端通过 Runtime API 回调确认
4. 回调成功后，Undefined 才会真正激活绑定并保存 `delivery_signature`
5. 如果远端暂时不可达，本地 pending 会保留；再次执行同一个 `/naga bind` 会沿用原来的 `bind_uuid` 继续重试

这意味着 `/naga bind` 的成功提示只代表“请求已提交到 Naga 端”，不代表绑定已经最终生效。

## /naga unbind

超级管理员执行：

```text
/naga unbind <naga_id>
```

行为：

- 本地立即吊销该绑定
- 尝试通知远端 Naga 端同步吊销
- 绑定用户会收到一条私聊通知

## 常见问题

**Q: 在群里发 `/naga` 没反应？**

A: 该群很可能不在 `naga.allowed_groups` 中；按设计这里会静默不可见。

**Q: 为什么 `/naga bind` 提示成功了，但还不能用？**

A: 因为它只是“已提交到 Naga 端”。真正生效要等远端回调确认。

**Q: 不配置 `models.naga` 可以吗？**

A: 可以。未配置时，Naga 外发消息审核会回退到 `models.security`。
