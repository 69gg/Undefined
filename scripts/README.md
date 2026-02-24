# scripts/

运维与维护脚本集合。

## 脚本列表

### [`reembed_cognitive.py`](reembed_cognitive.py) — 认知记忆向量库重嵌入

当更换嵌入模型（维度变化或模型升级）时，对 ChromaDB 中的 `cognitive_events` 和 `cognitive_profiles` 进行全量重嵌入。

**原理**：ChromaDB 存储了完整的原文本（`documents`），脚本读取所有记录，用新模型重新计算向量后 upsert 覆写，metadata 保持不变。

**前置条件**：先在 `config.toml` 中将 `[models.embedding]` 更新为新模型配置。

```bash
# 全量重嵌入（事件 + 侧写）
uv run python scripts/reembed_cognitive.py

# 仅重嵌入事件
uv run python scripts/reembed_cognitive.py --events-only

# 仅重嵌入侧写
uv run python scripts/reembed_cognitive.py --profiles-only

# 自定义批大小（默认 32，降低可减小 API 压力）
uv run python scripts/reembed_cognitive.py --batch-size 16

# 模拟运行（不实际写入，用于验证配置和统计数量）
uv run python scripts/reembed_cognitive.py --dry-run

# 详细日志
uv run python scripts/reembed_cognitive.py -v
```

**注意**：
- 运行期间不要同时启动机器人，避免 ChromaDB 写入冲突
- 大量记录时注意 API 限速，可通过 `--batch-size` 降低并发
- 建议先用 `--dry-run` 确认记录数量和配置正确性
