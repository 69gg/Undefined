# Docker 一次性部署（`uv run deploy`）实施计划

> 状态：已实现并归档（point-in-time 文档）。本计划记录把「本体 + NapCat + 按需自托管服务」做成一条命令容器化部署的决策与分步实施过程；实现以 `src/Undefined/deploy/` 与 [docs/docker-deploy.md](../../docker-deploy.md) 为准（2026-09）。

**Goal:** 在 Linux 上提供 `uv run deploy up`，让用户选择要跑哪些额外自托管服务（默认全不跑），由脚本完成 compose/配置生成、`config.toml` 最小差异写入、容器启动，并把各服务入口与凭据一次性输出。

**Architecture:** 模板与纯逻辑随包分发（`src/Undefined/deploy/templates/`，打进 wheel）；运行态一律落在仓库根 `deploy/`（gitignored）。分层：`catalog`（服务与默认值唯一事实来源）→ `generate` / `config_patch` / `nagaagent`（纯函数，产出内存态）→ `docker_cli`（唯一进程外 I/O 边界）→ `runner`（编排与输出）→ `cli`（参数与向导）。凭证写入幂等：按 `.env` → `config.toml` → 随机 的顺序取值，重跑不换已生效凭据。

**Tech Stack:** Python 3.11–3.13 + argparse + PyYAML（已在运行时依赖中）、复用的 WebUI `render_toml` / `apply_patch` / 注释映射、Docker Compose v2、GitHub Actions（Buildx + QEMU 多架构推 GHCR）。

---

## 决策记录（先问后做，全部由用户拍板）

| 决策点 | 结论 |
|---|---|
| 本体部署范围 | 两种都支持，`up` 时选择：`container` / `host` |
| 可选服务 | SearXNG、Firecrawl、lxmusic2api（NapCat 必需） |
| NagaAgent | 新增一问，默认不拉；拉取时只开问答能力，外部网关保持关闭 |
| 镜像仓库 | GHCR `ghcr.io/<owner>/undefined-bot`，无需额外 secret |
| 架构 | `linux/amd64` + `linux/arm64` |
| 第三方镜像 | 全部 pin 固定 tag（`playwright-service` / `nuq-postgres` 上游无版本 tag 除外） |
| lxmusic2api | 上游无镜像 → 我们 pin commit 后构建并推送 |
| Firecrawl | 用上游 GHCR 预构建镜像，并补上游缺失的持久化卷 |
| 文件发送模式 | `container` 模式自动改为 `url`（写前备份 `config.toml`） |
| Docker 访问 | DooD：只挂 `/var/run/docker.sock`，不启 DinD |
| 子命令 | `up` / `down` / `status` / `logs` |
| 交互 | 默认向导 + 参数覆盖；`--yes` 或非 TTY 走默认值 |
| 执行位置 | 仅目标机本机，不做远程 SSH 部署 |
| 模板分发 | 打进 wheel（`pip` 安装的包也能用） |
| 提交节奏 | 每完成一步立即 commit |

## 关键外部事实（调研阶段用 docker 实测确认）

- **NapCat**：`MODE=ws` 生成正向 WS 服务端（`0.0.0.0:3001`，模板里 token 为空）；WebUI 默认 6099，`NAPCAT_WEBUI_SECRET_KEY` 可预设 token（优先级高于 `WEBUI_TOKEN`），URL 为 `/webui?token=`；未登录时不监听 3001。
- **SearXNG**：`settings.yml` 缺失时会生成只含 `use_default_settings` 的极简文件，其余取包内默认 —— 其中 `search.formats` 默认只有 `html`，`format=json` 直接 403（而 `web_search` 走 JSON）；`limiter` 默认 false，因此不需要 valkey。
- **Firecrawl**：需 api + playwright-service + redis + rabbitmq + nuq-postgres 五容器；GHCR 有双架构预构建镜像；`USE_DB_AUTHENTICATION=false` 时不校验 key；无 dashboard，仅设 `BULL_AUTH_KEY` 后出现 Bull Board 队列页；上游未给 Postgres/Redis/RabbitMQ 定义持久卷。
- **lxmusic2api**：Node 22 + Fastify，无官方镜像；`server.host` 必须为 `0.0.0.0`、`auth.api_key` ≥32 字符、`legal.accept_lx_music_terms` 必须为 true；缺自定义音源仍可启动，仅取音频直链 503。

---

## 实施步骤（每步一个 commit）

- [x] `feat(deploy): 新增容器化部署服务目录与模板资源` — 包骨架、`catalog`（服务/端口/默认值唯一事实来源）、`images`（pin 与 GHCR 引用解析）、`state`（`deploy/` 布局、STATE.json、0600 写入）、`templates/`、`pyproject` 入口，模板随 wheel 分发。
- [x] `feat(deploy): 实现配置最小差异 patch 与备份` — 复用 WebUI 的 `apply_patch` + `render_toml` + 注释映射，只改拓扑键；冲突标记、写前备份、渲染后复验、无差异不写、`dry_run` 连备份都不写。
- [x] `feat(deploy): 实现 compose 与自托管服务配置生成` — 片段合并（拒绝重复定义与未知顶层键）、按模式对齐 `ws_url`/`file_send_mode`/服务地址、按需发布端口、SearXNG `formats: [html, json]`、Firecrawl env_file、lxmusic2api 三项必填。
- [x] `feat(deploy): 实现 NagaAgent 子模块就绪检查与开关写入` — 已就绪不跑 git；失败/超时/仍为空一律抛错并给出可手动执行的命令；只开 `[features].nagaagent_mode_enabled`，`[naga]` 网关与凭据始终关闭。
- [x] `feat(deploy): 实现 docker 调用层与 up 部署流程` — `docker_cli` 作为唯一 I/O 边界 + `DryRunRunner`；向导默认取上次 `STATE.json`；`--dry-run` 不落盘；启动后对齐 NapCat WS token；`status`/`logs`/`down`。
- [x] `ci(docker): 构建并推送 GHCR 多架构镜像` — `build-docker` job 位于 `verify-python` 之后、`publish-release` 之前；本体与 lxmusic2api 双架构；GHCR 私有包提示；仓库根 `.dockerignore`。
- [x] `chore(docker): 忽略 deploy 运行时目录并加固 --purge` — `/deploy/` 前导斜杠锚定仓库根（否则会连 `src/Undefined/deploy` 一起忽略，已加回归测试）；`--purge` 校验目标路径。
- [x] `docs(deploy): 新增容器化一键部署指南` — `docs/docker-deploy.md` + `docs/deployment.md` + `README.md` + `ARCHITECTURE.md` + `CLAUDE.md` + `scripts/README.md`。
- [x] `fix(deploy): 修正 Dockerfile 变量展开与 .dockerignore 误排` — BuildKit `--check` 抓到的两个真实问题，并把它变成静态闸门。
- [x] `docs(plan): 归档容器化部署实施计划` — 本文件。

## 测试与验收

新增 7 个测试文件（约 190 个用例），全部为纯函数/行为断言，不依赖 Docker daemon：

| 文件 | 覆盖 |
|---|---|
| `tests/test_deploy_catalog.py` | 服务与端口契约、模板存在性、pin 一致性、owner/版本解析 |
| `tests/test_deploy_config_patch.py` | 差异计算、冲突标记、注释保留、备份、坏 TOML 不落盘、幂等、计划合并 |
| `tests/test_deploy_generate.py` | 模式 × 服务组合的 compose 渲染、模板变量与 `.env` 的包含关系、各服务配置内容 |
| `tests/test_deploy_nagaagent.py` | 子模块状态机、git 调用只在需要时发生、失败语义、两分支开关 |
| `tests/test_deploy_runner.py` | `.env` 解析、向导（含 EOF/坏输入）、WS token 对齐、`docker_cli` 封装、`up --dry-run` 全流程 |
| `tests/test_deploy_state.py` | 目录布局、STATE 往返与容错、原子写入与 0600 |
| `tests/test_deploy_packaging.py` | 模板存在性、`.dockerignore` 与 Dockerfile COPY 的一致性、`docker build --check`（有 daemon 时）、wheel 内容（`UNDEFINED_DEPLOY_WHEEL_CHECK=1`） |

验收命令：`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest tests/`，加上 `uv run deploy up --dry-run` 覆盖两种模式与全部服务组合。

## 明确的范围外

远程 SSH 部署、反向代理/HTTPS、Windows/macOS 适配、微信 iLink 容器编排、Firecrawl 的 LLM 可选功能、自动代填 `[models.*]`、把 NagaAgent 容器化。

## 遗留与已知问题

- `tests/test_source_assertion_budget.py` 的预算在本次工作开始前已被上一版（`feat(config): 按功能拆分 embedding 模型配置…`）推到超支（干净旧版实测 808 > 800，门禁为红）。本次实现把该数字降到正好 800、测试转绿，但**没有为新增测试申请新的预算额度**——新增测试全部使用行为断言。
- GHCR 包首次推送默认为 private，用户需 `docker login ghcr.io` 或把包改为 public，已在 CI summary 与文档中提示。
- 重型验证（真实构建镜像、起整套 compose）按用户要求不在开发机执行，留给 CI 与目标机。
