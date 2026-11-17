# chiliarch 独立渠道设计

chiliarch 作为必需依赖，内嵌原生 AgentClient handler、AgentMailbox 和 ClientStore。
单并发，配对成功后发布 `data/chiliarch/client.db`；文件存在自动启用，删除自动停用，运行中也检测变化。
不添加主配置项或环境变量，不修改 config.toml 及配置示例；配对凭证不进入状态 API。
心跳与断线重连由原生客户端维护。上游使用无固定到期时间的长期凭证，没有续期接口；吊销后需重新配对。
同一 state 只有一个网络 owner；WS、SSE、poll、ACK、幂等、取消和 interrupted 语义沿用上游。

总管是独立普通用户 `chiliarch_main`，属于 `entity_type=user`。
通用可选 `logical_identity` 与平台数字身份分开；不使用虚拟 QQ、不继承 WebUI 超管。
任务分别保存聊天，正式 `continue_task_id` 复用会话，总管普通消息使用持续会话。
正常经过 end、史官、事件记忆、侧写；可主动读其他侧写。同伴信息保留来源。
现有 WebUI 行为、旧数据、QQ/微信访问控制兼容。

支持正式任务、取消、进度、结果、联系总管、同伴私信/讨论、回执、请求结果、等待关系和共享文件。
不声明 task_workdir 能力；收到非空 workdir 失败，不修改进程目录。
总管未关联消息启动普通聊天；已关联回信通知持久记录的原聊天或任务收件箱，不递归回复。
同伴消息不自行唤醒 AI，wake 由平台派发正式任务。重启不重做未知副作用。
发送前保存确定的 envelope/request ID 和 origin；无关联消息不猜最近聊天。
当前逻辑会话回复走 session sender，显式物理目标仍走原 sender 和 ACL。
共享文件复用原生分块/大小/SHA 校验；下载进入本地缓存并登记会话作用域 attachment UID。

首版无新增 UI，提供 Runtime 鉴权保护的 `/api/v1/chiliarch/status`。
渠道运行独立于 api.enabled；未配对为 disabled，损坏或拒绝的身份为 unavailable，不影响其他渠道。
测试不连接真实平台，不修改生产 state。
