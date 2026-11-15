# chiliarch 独立渠道设计

chiliarch 通过可选依赖内嵌原生 AgentClient handler、AgentMailbox 和 ClientStore。
默认关闭，单并发，状态由官方配对流程生成；凭证不进入 Undefined 主配置或状态 API。
同一 state 只有一个网络 owner；WS、SSE、poll、ACK、幂等、取消和 interrupted 语义沿用上游。

总管是独立普通用户 `chiliarch_main`（可配置），属于 `entity_type=user`。
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
渠道运行独立于 api.enabled；缺依赖/未配对仅使该渠道 unavailable。
身份和连接配置要求重启。测试不连接真实平台，不修改生产 state。
