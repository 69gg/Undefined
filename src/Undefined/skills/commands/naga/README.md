`/naga` 用于把 QQ 用户与 NagaAgent 的远端身份绑定起来，并在需要时解除绑定。

当前可用命令：
- `/naga bind <nagaagent_id>`
- `/naga unbind <nagaagent_id>`

## /naga bind
执行：
/naga bind <您的_nagaagent_id>
会向 NagaAgent 服务器发送绑定请求，后续操作请参考 NagaAgent 相关文档。

## /naga unbind
超级管理员执行：
```text
/naga unbind <nagaagent_id>
```
会解绑该 NagaAgent ID。亦可由 NagaAgent 服务端发起。
