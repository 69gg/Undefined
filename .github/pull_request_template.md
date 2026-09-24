## 变更说明

<!-- 用一两句话说明这个 PR 做了什么、为什么需要 -->

## 影响范围

<!-- 受影响的模块 / 配置项 / 用户可见行为；不涉及请写“无” -->

## 关联 Issue

<!-- Closes #123 / Refs #456；没有可留空 -->

## 自检

- [ ] `uv run ruff check .` 与 `uv run ruff format --check .` 通过
- [ ] `uv run mypy .` 通过
- [ ] `uv run pytest tests/ --cov` 通过（覆盖率不低于 `pyproject.toml` 中的 `fail_under`）
- [ ] 改动 `apps/undefined-console/` 或 `src/Undefined/webui/static/js/`：已跑 `cd apps/undefined-console && npm run check`
- [ ] 改动 `apps/undefined-chat/`：已跑 `cd apps/undefined-chat && npm run check`
- [ ] 涉及配置项：已同步 `config.toml.example` 与 `docs/configuration.md`
- [ ] 涉及 WebUI / Tauri 界面：已附截图

## 备注

<!-- 部署注意事项、需要重启的配置、回滚方式等 -->
