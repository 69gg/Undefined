# group_analysis 工具集

群聊深度分析工具集合，工具名以 `group_analysis.*` 命名。

主要能力：
- `group_analysis.member_structure`：统计角色分布、等级概览、入群时间覆盖和最后发言分层等成员结构事实；详细等级分布请使用 `group_analysis.level_distribution`。
- `group_analysis.message_mix`：统计消息类型分布、活跃时段、活跃星期、时间覆盖和最近消息样本。
- `group_analysis.member_activity`：区分最近发言、历史窗口消息数及混合指标排行。
- `group_analysis.rank_members`：对群成员进行多维度排名。
- `group_analysis.filter_members`：按角色、等级、入群时间、活跃时间等条件过滤群成员。
- `group_analysis.inactive_risk`：检测长期潜水或新成员沉默等活跃风险。
- `group_analysis.activity_trend`：分析群活跃趋势变化。
- `group_analysis.level_distribution`：统计群成员等级分布。
- `group_analysis.member_messages`：分析指定成员的消息数量、类型分布和活跃时段。
- `group_analysis.join_statistics`：统计群成员加入趋势与留存情况。
- `group_analysis.new_member_activity`：分析新成员加入后的活跃度变化。

这些工具主要给 AI 调用。需要用户直接触发时，应由 AI 根据问题选择合适工具，并将工具输出整理成自然语言回复。

## `member_activity` 的统计口径

| `source` | 排序与含义 | 适用问题 |
|---|---|---|
| `member_list` | 仅根据 OneBot 成员列表中的 `last_sent_time`，对近期有发言记录的成员按时间倒序排列 | 谁最近说过话 |
| `history` | 按本次读取到的窗口消息数排序，同数时依次比较活跃天数、窗口内最后发言时间；不使用成员列表的最后发言时间排序或推断窗口活跃情况 | 指定时间内谁发言最多 |
| `hybrid`（默认） | 沿用消息数、活跃天数和成员列表最后发言时间加权的综合分，输出“混合指标排行” | 综合查看发言情况 |

- `last_sent_time` 只表示最后一次发言的时间，不能据此判断发言频率或当前在线状态。“刚说过一句”不意味着“发言最多”。字段定义见 [OneBot 11 成员信息接口](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)。
- `threshold_days` 的成员列表统计以当前时间为基准，与 `start_time` / `end_time` 限定的历史窗口分开展示；`history` 模式不附带这份当前概况。
- 最后发言时间缺失或为 0 的成员单独列为“未知”，不算作最后发言较早的成员，也不能断言其从未发言。
- 历史统计仅覆盖本次成功读取到的消息，受 `max_history_count` 和接口可用范围限制，可能未覆盖整个窗口。`include_zero=true` 展示的 0 条表示“窗口内未检索到发言”，不是整个窗口内确定没有发言。
- `history` 和 `hybrid` 会跳过时间缺失、无效或越界的历史消息，不计入消息数、活跃天数或最后发言时间；支持秒级、毫秒级及数值字符串时间戳，不用当前时间补全未知记录。
- AI 转述时应保留时间范围、数据来源和排行含义，不能把“最近发言成员”或“混合指标排行”改说成“发言数量榜”。
