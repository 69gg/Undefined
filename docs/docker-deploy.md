# 容器化一键部署（`uv run deploy`）

用一条命令把 **Undefined 本体 + NapCat**，以及按需选择的 **SearXNG / Firecrawl / lxmusic2api** 跑起来，并自动把服务地址与凭据写回 `config.toml`。

```bash
uv run deploy up          # 交互式向导：选部署模式与额外服务
uv run deploy status      # 查看容器状态、入口地址与凭据
uv run deploy logs        # 跟踪日志（可加服务名与 --tail）
uv run deploy down        # 停止服务（数据保留）
```

> 适合 Linux。默认**只部署本体 + NapCat**，其余服务与 NagaAgent 全部不启用。
>
> 需要先具备：Linux + Docker Engine（含 `docker compose` v2 插件）+ `git`。Python 环境由 `uv` 按 `pyproject.toml` 约束自动准备。

---

## 1. 快速开始

```bash
git clone --recursive https://github.com/69gg/Undefined.git
cd Undefined

uv run deploy up
```

向导只会问三件事：

1. **本体部署方式** —— `container`（本体也在 compose 里，默认）或 `host`（本体跑宿主机，只用 Docker 跑依赖服务）
2. **额外部署哪些自托管服务** —— 输入编号多选，直接回车表示全不部署
3. **是否拉取 NagaAgent 子模块** —— 默认否

确认后脚本会：生成 `deploy/` 下的 compose 与各服务配置 → 按差异修改 `config.toml`（改前自动备份）→ 校验 compose → 启动容器 → 输出全部入口与凭据。

全程非交互（CI、无人值守、脚本化）时加 `--yes` 走默认值：

```bash
uv run deploy up --yes                                   # 本体 + NapCat
uv run deploy up --yes --with searxng                    # 额外部署 SearXNG
uv run deploy up --yes --with searxng,firecrawl          # 多个服务
uv run deploy up --yes --mode host                       # 本体跑宿主机
uv run deploy up --dry-run --with lxmusic2api            # 只打印计划，不落盘不起容器
```

### 常用参数

| 参数 | 说明 |
|---|---|
| `--mode container\|host` | 本体部署方式，默认 `container` |
| `--with SVC[,SVC...]` / `--with-<svc>` | 选择额外服务；可选项 `searxng`、`firecrawl`、`lxmusic2api` |
| `--with-nagaagent` / `--no-nagaagent` | 是否拉取 NagaAgent 子模块并开启其问答能力（默认否） |
| `--port KEY=PORT` | 覆盖端口，可重复；`KEY` 见 `uv run deploy up --help` |
| `--port-bind ADDR` | 所有发布端口的绑定地址，默认 `127.0.0.1` |
| `--pull missing\|always\|never` | 镜像拉取策略，默认 `missing`（本地没有才拉） |
| `--dry-run` | 只打印将写入的 `config.toml` 差异与生成的 compose/.env（凭据显示为 `<secret>`） |
| `--yes` / `-y` | 跳过向导，未指定项走默认值（或上次部署的选择） |

`down` 另有 `--volumes`（同时删除 compose 管理的 named volumes）与 `--purge`（连同 `deploy/` 数据与凭据一并删除，不可恢复）。

---

## 2. 生成的目录结构

模板在 `src/Undefined/deploy/templates/`（随 wheel 分发，也可 pip 安装后使用）；**运行态一律落在仓库根的 `deploy/`**，已加入 `.gitignore`：

```
deploy/
├── STATE.json      # 已选服务、部署模式、端口、镜像 owner（重跑时的默认值来源）
├── .env            # 端口、绑定地址与全部凭据（权限 0600）
├── compose.yaml    # 由模板片段合并生成
├── searxng/settings.yml
├── firecrawl/.env
├── lxmusic2api/{config.toml,.private/}
├── napcat/config/  # NapCat 自己的 onebot11.json / webui.json
├── napcat/qq/      # QQ 登录态
├── backup/config_<时间戳>.toml
└── data/           # 仅 container 模式：挂给本体的 /data/Undefined/data
```

**幂等与凭据**：`up` 每次都会重新渲染 compose 与配置，但凭据按「`deploy/.env` 已有 → `config.toml` 已生效 → 随机生成」的顺序取值，因此重跑不会把已经生效的 WebUI 密码、Runtime `auth_key`、NapCat token、SearXNG `secret_key`、lxmusic2api key 换掉。`changeme` 一类占位值会被替换。

> `host` 模式下本体的运行态仍在仓库根 `data/`（`utils/paths.py` 里的路径是相对工作目录解析的），只有 `container` 模式才落到 `deploy/data/`。

---

## 3. 两种部署模式

| | `container`（默认） | `host` |
|---|---|---|
| 本体 | 也在 compose 里，镜像 `ghcr.io/<owner>/undefined-bot` | 宿主机上另开终端跑 `uv run Undefined-webui` |
| `[onebot].ws_url` | `ws://napcat:3001` | `ws://127.0.0.1:3001` |
| `[onebot].file_send_mode` | `url`（协议端在另一个容器，走 Runtime 临时链接） | `local`（本体与仓库同文件系统） |
| `[webui].url` / `[api].host` | `0.0.0.0`（容器内监听，端口由 compose 发布） | `127.0.0.1` |
| 自托管服务地址 | compose 服务名直连（`http://searxng:8080` 等） | 发布端口（`http://127.0.0.1:8080` 等） |

`container` 模式下本体容器以 `/data/Undefined` 为工作目录，把仓库的 `config.toml`、`res/`、`img/`、`config/`、`knowledge/` 以及 `deploy/data`、`deploy/logs` 挂进去，所以在宿主机上直接编辑 `config.toml` 就生效，也不会覆盖镜像内的 Python 环境。

---

## 4. 各服务说明

### NapCat（必需）

- 官方镜像 `mlikiowa/napcat-docker`，`MODE=ws`：NapCat 作为**正向 WebSocket 服务端**监听 3001，本体作为客户端连过去。
- WebUI 默认 6099，token 由脚本生成并通过 `NAPCAT_WEBUI_SECRET_KEY` 预设，**不需要进容器翻 token**；入口形如 `http://127.0.0.1:6099/webui?token=<token>`。
- 首次使用需要在 WebUI 里扫码登录，或直接看容器日志里的二维码：

```bash
docker logs -f napcat
```

- **未登录时协议端不会监听 3001**，此时本体连不上是正常现象。
- 容器启动后脚本会把 `[onebot].token` 对应的值补写进 `deploy/napcat/config/onebot11.json`（模板里该字段为空）。如果首次 `up` 时该文件还没生成，脚本会提示；等 NapCat 启动后再跑一次 `up` 即可对齐。

### SearXNG（`--with searxng`）

内置 `web_search` 工具的后端。复用官方镜像，但**必须自备 `settings.yml`**：镜像在挂载目录为空时会生成一份只含 `use_default_settings` 的极简配置，而其中的 `search.formats` 默认只有 `html`，对 `format=json` 的请求会直接返回 403，而 `web_search` 走的正是 JSON 格式。

脚本生成的 `deploy/searxng/settings.yml` 因此显式包含：

```yaml
use_default_settings: true
search:
  formats: [html, json]
server:
  secret_key: <随机>      # 由脚本生成
  limiter: false          # 保持关闭，因此不需要 valkey
  base_url: http://127.0.0.1:8080
```

入口：`http://127.0.0.1:8080/`。

### Firecrawl（`--with firecrawl`）

`firecrawl_search` 工具的后端。复用上游 GHCR 预构建镜像，会拉起 **5 个容器**：`firecrawl-api`、`firecrawl-playwright`、`firecrawl-redis`、`firecrawl-rabbitmq`、`firecrawl-postgres`。

- 上游 compose 默认走本地 `build:`，我们改用官方预构建镜像；同时补上上游缺失的持久化卷（Postgres 存 NuQ 队列状态，Redis/RabbitMQ 存限流与消息）。
- `USE_DB_AUTHENTICATION=false` 时 Firecrawl **完全不校验 API Key**，因此 `[search.firecrawl].api_key` 随便填即可。这是官方行为，适用于可信网络，**不要把无鉴权的 API 暴露到不可信网络**。
- 资源占用较高（上游给 api 设 4 CPU / 8G、playwright 设 2 CPU / 4G，官方声明这不是最低要求），可按机器情况调整 `deploy/compose.yaml` 里 `firecrawl-api` 的 `cpus` / `mem_limit`（改完重跑 `up` 会按模板重新生成，长期调整请改模板）。
- **自托管 Firecrawl 没有 dashboard / playground**，唯一的管理界面是 Bull Board 队列页：`http://127.0.0.1:3002/admin/<BULL_AUTH_KEY>/queues`（`BULL_AUTH_KEY` 见 `deploy/firecrawl/.env`）。

### lxmusic2api（`--with lxmusic2api`）

`music.*` 工具集的后端。**上游没有任何预构建镜像**（仓库无 `.github`、无 tag、无 release），因此镜像由本项目在 CI 里 clone 上游固定 commit 后构建，推送到 `ghcr.io/<owner>/undefined-lxmusic2api:<短sha>`。

- 脚本生成的 `deploy/lxmusic2api/config.toml` 含三项必需配置：`server.host = "0.0.0.0"`、`legal.accept_lx_music_terms = true`、随机且长度 ≥32 的 `auth.api_key`。缺任一项上游会拒绝启动。
- **取音频直链需要自备 LX 自定义音源脚本**：把兼容「LX 自定义源 API v2」的 `.js` 放到 `deploy/lxmusic2api/.private/custom-source.js`（或改用目录模式），然后重启该容器。没有音源时服务仍会启动，搜索/歌单/歌词可用，但取音频直链会返回 503，`up` 的输出里也会明确提示。
- 唯一浏览器界面是只读的 Swagger 文档：`http://127.0.0.1:3000/docs`。
- 上游许可证为 Apache-2.0 附加 LX Music 补充协议（仅技术学习/非商业、版权数据 24 小时内清除、须自行确认音源合法性），使用前请阅读上游 `LICENSE` 与 `LICENSES/`。

### NagaAgent（`--with-nagaagent`）

NagaAgent 是仓库的 git submodule（`code/NagaAgent`），不是独立服务。选择拉取后：

- 脚本检查子模块是否已初始化，未就绪时执行 `git submodule update --init --recursive code/NagaAgent`；失败会中止并给出可手动执行的命令（不会静默继续）。
- 写入 `[features].nagaagent_mode_enabled = true`，即启用 NagaAgent 专用系统提示词与 `naga_code_analysis_agent`（该 Agent 的四个工具把 `base_path` 固定在 `Path.cwd()/code/NagaAgent`，所以能力开关与子模块存在性绑定）。
- **`[naga].enabled` 与 `api_url` / `api_key` 始终保持关闭与留空**，即不开启对外回调网关、`/naga` 命令与绑定管理。若日后确实要与 Naga 服务端对接，需要你自己填这些字段。
- `container` 模式下 `code/NagaAgent` 会以只读方式挂进本体容器同一路径。

不选择时，`[features].nagaagent_mode_enabled` 与 `[naga].enabled` 都写入 `false`，相关提示词、Agent、命令与 API 端点全部隐藏。

---

## 5. 部署脚本会改哪些配置

`up` 只写**服务拓扑相关**的键，其余内容（包括全部注释与你的自定义项）原样保留：

| 键 | 说明 |
|---|---|
| `[onebot].ws_url` | 按模式写入 `ws://napcat:3001` 或 `ws://127.0.0.1:3001` |
| `[onebot].token` | 与 NapCat 正向 WS 服务端一致的访问令牌（自动生成） |
| `[onebot].file_send_mode` / `file_send_host` | `container` 模式写入 `url` / `host.docker.internal` |
| `[webui].url` / `[webui].password` | 监听地址按模式；密码为空或 `changeme` 时生成随机值 |
| `[api].host` / `[api].auth_key` | 同上 |
| `[features].nagaagent_mode_enabled` | 见上一节 |
| `[search].searxng_url` | 选了 SearXNG 时写入 |
| `[search].firecrawl_search_enabled` / `[search.firecrawl].base_url` | 选了 Firecrawl 时写入 |
| `[lxmusic2api].base_url` / `.api_key` | 选了 lxmusic2api 时写入 |

**不会碰**：`[models.*]`（模型端与 API Key 需要你自己填）、`[access]`、`[prompt]`、`[history]` 等。

写盘前会先把原文件备份到 `deploy/backup/config_<UTC 时间戳>.toml`；解析失败时直接中止且不写任何文件。`--dry-run` 连备份都不写。

---

## 6. 镜像与 CI

发布镜像在 `v*` tag 推送时由 `.github/workflows/release.yml` 的 `build-docker` job 构建，位置在 `verify-python` 之后、`publish-release` 之前：

| 镜像 | 内容 |
|---|---|
| `ghcr.io/<owner>/undefined-bot:<tag>` | 本体：Python 3.12 + 依赖 + ffmpeg + docker CLI + Playwright Chromium |
| `ghcr.io/<owner>/undefined-lxmusic2api:<短sha>` | lxmusic2api，clone 上游 pin 的 commit 后构建 |

两者都构建 `linux/amd64` 与 `linux/arm64`。推送使用内置 `GITHUB_TOKEN`（workflow 已声明 `packages: write`），**不需要额外配置 secret**。

> **GHCR 包首次推送默认为 private。** 拉取前需要 `docker login ghcr.io`，或者到 GitHub 的包设置里把可见性改成 public，否则 `up` 拉镜像会 401。
>
> 从源码部署时也可以完全不用预构建镜像，改为本地构建：
> `docker build -f src/Undefined/deploy/templates/Dockerfile.bot -t ghcr.io/<owner>/undefined-bot:v<版本> .`

**升级 lxmusic2api 上游**：改 `src/Undefined/deploy/images.py` 里的 `LXMUSIC2API_UPSTREAM_SHA`，再跑一次 release（或手动触发 workflow）。CI 会检查该值仍是占位符时跳过该镜像构建，不会产出不可复现的 `main` HEAD 镜像。

**升级第三方镜像 pin**：NapCat / SearXNG / Firecrawl 及其依赖的 tag 同样集中在 `images.py`，`pin` 常量带 `PIN_VERIFIED_ON` 记录核对日期。`playwright-service` 与 `nuq-postgres` 上游不发布版本 tag，只能跟随 `latest`。

---

## 7. 日常运维

```bash
uv run deploy status                 # 容器状态 + 全部入口与凭据
uv run deploy logs                   # 全部服务日志（跟随）
uv run deploy logs napcat --tail 200 # 只看 NapCat 最近 200 行
uv run deploy down                   # 停止，保留 deploy/ 与数据
uv run deploy down --volumes         # 同时删除 named volumes
uv run deploy down --purge           # 连同 deploy/ 一起删除（不可恢复）
```

**改部署选择**：直接重跑 `uv run deploy up`，向导会以 `STATE.json` 为默认值；或者带参数一次性覆盖。旧的 `deploy/` 目录会被收敛到新选择（未被选中的服务模板不会出现在新 compose 里）。

**改端口**：`uv run deploy up --port napcat_ws=13001 --port bot_webui=18787`，或直接改 `deploy/.env` 后重跑（会被下次 `up` 覆盖，建议用参数）。

**远程访问**：默认所有端口只绑 `127.0.0.1`。要远程访问改成 `--port-bind 0.0.0.0` 或改 `.env` 里的 `*_BIND`，但请注意 Undefined WebUI、NapCat WebUI、Firecrawl API 都不是为公网暴露设计的，请自行加防火墙或反向代理。

**更新镜像**：`uv run deploy up --pull always`（会检查每个 tag 的更新；pin 的 tag 内容不变时不会产生变化）。

---

## 8. Docker 访问方式（DooD）

`container` 模式下本体容器挂载宿主机的 `/var/run/docker.sock`，即 **DooD（Docker-out-of-Docker）**：`python_interpreter` 与 `code_delivery_agent` 通过宿主 daemon 启动兄弟容器，不额外跑一个 `dockerd`。

- 优点：资源开销几乎为零，不需要 `privileged`，`python_interpreter` 的 `--network none` 隔离照常生效。
- 代价：能看到并能操作宿主机上的**全部容器**，权限等级等同于宿主机 root。这两个工具本身的设计就是「让模型在沙箱容器里执行代码」，但 `--network none` 只隔离网络，不是权限隔离；只应部署在你自己可控的机器上。
- 若不想给这个能力，去掉 `deploy/compose.yaml` 里本体服务的 docker.sock 挂载行即可，代价是 `python_interpreter` / `code_delivery_agent` 会以「找不到 docker 命令」失败（属预期行为）。
- 这两个工具使用的基础镜像（`python:3.11-slim`、`ubuntu:24.04`）会在首次调用时按需拉取。

---

## 9. 故障排查

| 现象 | 原因与处理 |
|---|---|
| `up` 报「找不到 docker」/「找不到 docker compose 插件」 | 未安装 Docker Engine 或缺少 v2 插件；`host` 模式同样需要 Docker 来跑依赖服务与协议端 |
| 拉镜像 401 / denied | GHCR 包是 private：先 `docker login ghcr.io`，或把包改成 public |
| 本体日志报连不上 `ws://napcat:3001` | NapCat 尚未登录，协议端未开始监听；先 `docker logs -f napcat` 扫码 |
| `web_search` 报未启用 / SearXNG 调用 403 | 检查 `deploy/searxng/settings.yml` 的 `search.formats` 是否含 `json`，改后 `docker compose restart searxng` |
| Firecrawl 启动慢或 OOM | 该 stack 资源占用高；可减少 `NUM_WORKERS_PER_QUEUE`，或在 `deploy/compose.yaml` 里调低 `firecrawl-api` 的 `mem_limit` |
| `music.get_audio` 返回 503 | 没有自定义音源脚本：把 `.js` 放进 `deploy/lxmusic2api/.private/` 后重启该容器 |
| WebUI 打不开 | 密码在 `deploy/.env` 的 `UNDEFINED_DEPLOY_WEBUI_PASSWORD`；默认密码 `changeme` 不允许登录，部署脚本已生成随机值 |
| `config.toml` 被改错 | 从 `deploy/backup/` 取最近一份备份覆盖回去 |

---

## 10. 当前范围之外

- 远程（SSH）部署：脚本只在目标机本机执行。
- 反向代理 / HTTPS / 证书：自行在 Docker 前面加。
- Windows / macOS 适配：脚本按 Linux 编写（uid/gid、`/var/run/docker.sock` 等）。
- 微信 iLink 的容器编排：仍按 [配置说明](configuration.md) 在宿主机或容器内自行启用。
- Firecrawl 的 LLM 相关可选功能（`OPENAI_API_KEY` 等）：默认不预设，需要时写进 `deploy/firecrawl/.env`。
- 不代填模型配置：部署完成后仍需在 `config.toml` 的 `[models.*]` 里填模型端与 API Key，Bot 才能真正收发消息。
