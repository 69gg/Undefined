# scripts/

运维与维护脚本集合。

## 脚本列表

### [`sync_config_template.py`](sync_config_template.py) — 同步配置模板与注释

保留当前 `config.toml` 已有配置值，同时把 `config.toml.example` 中新增的配置项、默认空表和双语注释同步回来。

```bash
# 直接用 Python 运行
python scripts/sync_config_template.py

# 若希望复用项目虚拟环境，也可这样运行
uv run python scripts/sync_config_template.py

# 仅预览，不落盘
python scripts/sync_config_template.py --dry-run

# 输出同步后的完整内容
python scripts/sync_config_template.py --stdout
```

**适用场景**：
- 项目升级后想把新增配置项补齐到现有 `config.toml`
- 想恢复 `config.toml.example` 中的最新双语注释
- 不想手工比对新旧配置文件

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

### release_notes.py — 发布版本校验与 Release notes 生成

Release workflow 使用这个脚本在构建前校验版本一致性，并在发布阶段从 `CHANGELOG.md` 最新版本条目生成 GitHub Release 说明。Release notes 会先写入 changelog 自动提取内容，再用 `---` 分隔并追加 `Detailed Changes`，按上一个 tag 到当前 tag 的 commit 主题分类列出 features、bug fixes 和 maintenance/others。

```bash
# 校验 tag、构建版本和 CHANGELOG 最新版本一致
uv run python scripts/release_notes.py validate --tag v3.4.0

# 从 CHANGELOG 最新条目生成 Release notes，并追加 Detailed Changes
python3 scripts/release_notes.py notes --tag v3.4.0 --output release_notes.md
```

**校验范围**：

- `pyproject.toml`
- `src/Undefined/__init__.py`
- `apps/undefined-console/package.json`
- `apps/undefined-console/package-lock.json`
- `apps/undefined-console/src-tauri/Cargo.toml`
- `apps/undefined-console/src-tauri/tauri.conf.json`
- `CHANGELOG.md` 最新版本条目
