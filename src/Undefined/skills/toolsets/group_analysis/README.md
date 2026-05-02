# group_analysis 工具集

群聊深度分析工具集合，工具名以 `group_analysis.*` 命名。

主要能力：
- `group_analysis.member_structure`：统计角色分布、等级概览、入群时间覆盖和最后发言分层等成员结构事实；详细等级分布请使用 `group_analysis.level_distribution`。
- `group_analysis.message_mix`：统计消息类型分布、活跃时段、活跃星期、时间覆盖和最近消息样本。
- `group_analysis.member_activity`：分析群成员活跃度。
- `group_analysis.rank_members`：对群成员进行多维度排名。
- `group_analysis.filter_members`：按角色、等级、入群时间、活跃时间等条件过滤群成员。
- `group_analysis.inactive_risk`：检测长期潜水或新成员沉默等活跃风险。
- `group_analysis.activity_trend`：分析群活跃趋势变化。
- `group_analysis.level_distribution`：统计群成员等级分布。
- `group_analysis.member_messages`：分析指定成员的消息数量、类型分布和活跃时段。
- `group_analysis.join_statistics`：统计群成员加入趋势与留存情况。
- `group_analysis.new_member_activity`：分析新成员加入后的活跃度变化。

这些工具主要给 AI 调用。需要用户直接触发时，应由 AI 根据问题选择合适工具，并将工具输出整理成自然语言回复。
