# 参与贡献

感谢参与 Undefined！本文说明提 PR 前的最低要求；模块职责与开发细节见 [docs/development.md](docs/development.md) 与 [CLAUDE.md](CLAUDE.md)。

## 环境准备

```bash
uv sync                       # 安装运行期 + dev 依赖（同一份 dev 组供 CI 使用）
uv run playwright install     # 截图 / 网页抓取所需的浏览器运行时
bash scripts/install_git_hooks.sh   # 启用 .githooks/pre-commit（ruff + mypy + 条件性前端检查）
```

前端（按需）：

```bash
cd apps/undefined-console && npm ci && npm run check   # Biome + tsc + cargo fmt/check
cd apps/undefined-chat    && npm ci && npm run check   # Biome + tsc + Vitest 单测/E2E + cargo
```

## 提交前自检

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests/ --cov
```

- 覆盖率门禁写在 `pyproject.toml` 的 `[tool.coverage.report].fail_under`（当前 65%），改动会降压时请补测试而不是调低阈值。
- 只改 WebUI 脚本（`src/Undefined/webui/static/js/`）与两个原生 App 时，除 Python 检查外还要跑对应 App 的 `npm run check`。
- 提交信息使用 Conventional Commits（如 `fix(queue): ...`、`feat(config): ...`），保持祈使句与简洁主题。

## 代码约定（摘要）

- Python 4 空格缩进、全量类型注解、严格 mypy；磁盘 I/O 走 `src/Undefined/utils/io.py`。
- Skills handler 只能依赖标准库、第三方包、`Undefined.skills.*`、同目录相对导入与 `context` 注入；跨技能共享助手放 `src/Undefined/skills/shared.py`。越界导入由 `tests/test_skills_import_boundary.py` 的棘轮基线拦截。
- 新增/修改配置项必须同时更新 `config.toml.example`（中英双语注释）与 `docs/configuration.md`；热更新语义变化要在文档中写明。
- 架构行为变化请在 PR 描述中给出理由与验证方式，并在必要时更新 `ARCHITECTURE.md` / 相关文档。

## Pull Request

- 使用仓库的 PR 模板，填写变更说明、影响范围、关联 Issue 与自检项。
- PR 会运行 CI：`quality-check`（lint / mypy / pytest + 覆盖率 / wheel 构建）、`python-compat`（3.11 与 3.13）、`native-app-quality-check`（Console 与 Chat）。
- CI 未通过前不要请求评审；确需抢跑时请在描述中说明原因。
- 用户可见的界面改动请附截图。

## 报告问题

- 功能缺陷与建议：使用仓库 Issue（附复现步骤、配置片段、日志关键字，注意脱敏 token / API Key）。
- 安全相关问题：请不要公开提交细节，先私下联系维护者。
