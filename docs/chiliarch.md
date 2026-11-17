# chiliarch 接入

chiliarch 总管作为独立普通用户 `chiliarch_main` 与 Undefined 聊天，拥有自己的历史、记忆和侧写，也可主动读取其他侧写。支持任务、同伴协作、回信和共享文件。

## 配对一次即可使用

在 Undefined 的运行目录执行：

```bash
uv sync
uv run Undefined-chiliarch-pair --server https://your-chiliarch.example
```

按提示输入平台生成的一次性注册码。名称默认为 `Undefined`，需要区分多台机器时加 `--name 名称`。

配对成功后生成 `data/chiliarch/client.db`，Undefined 检测到这个文件就自动接入。Bot 正在运行时也能检测，无需重启；尚未运行时照常用 `uv run Undefined-webui` 启动，再在管理界面启动 Bot。**不修改 `config.toml`，没有额外配置项，也不需要单独运行 chiliarch 客户端或守护进程。**

Undefined 自动维护心跳、断线重连和重启恢复。一次性注册码兑换后就不再需要；配对得到的长期凭证没有固定到期时间，无需定期续期。凭证被平台吊销后，先删除 `data/chiliarch/client.db`，等待渠道停用，再重新执行上面的配对命令。若注册码兑换成功但配对文件发布失败，日志会给出保留的 `.pairing` 数据库路径；数据库及其 `-wal`、`-shm` 附属文件包含已兑换凭证，恢复前请一并保留。

## 停用

删除配对文件即可，运行中的连接也会自动停止：

```bash
rm data/chiliarch/client.db
```

聊天历史、业务关联和下载缓存保留在相邻的 `client.db.undefined/` 中。配对文件包含凭证，不要共享；同一文件只由 Undefined 使用。

总管普通消息使用持续聊天，正式任务分别保存会话；中断的任务不会自动重做。模型调用重试耗尽或达到工具迭代上限会将任务标为失败，正常调用 `end` 即使没有回复正文也算成功。QQ、微信和 WebUI 也可通过 [chiliarch.call 工具](../src/Undefined/skills/toolsets/chiliarch/README.md) 联系总管，关联回信返回原聊天。渠道在 OneBot 连接建立后开始监听；运行中 OneBot 断线时，QQ 和群聊回信在独立投递任务中等待重连，不阻塞后续收件、微信回信和总管聊天，同一原会话的回信保持顺序。重启会恢复尚未开始投递的回信，同一事件只写入一条历史，已送达或投递结果不确定的回信不会自动重发。任务不能改变 Undefined 的工作目录。

需要排查连接时，可通过已有 Runtime API 鉴权调用 `GET /api/v1/chiliarch/status`；`mailbox_ready` 表示本地收件箱就绪。
