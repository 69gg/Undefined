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

向导只会问四件事：

1. **本体部署方式** —— `container`（本体也在 compose 里，默认）或 `host`（本体跑宿主机，只用 Docker 跑依赖服务）
2. **额外部署哪些自托管服务** —— 输入编号多选，直接回车表示全不部署（重跑时回车表示沿用上次的选择）
3. **发布端口的绑定地址** —— 默认 `127.0.0.1`（仅本机可访问）
4. **是否拉取 NagaAgent 子模块** —— 默认否

确认后脚本会：生成 `deploy/` 下的 compose 与各服务配置 → 按差异修改 `config.toml`（改前自动备份）→ 校验 compose → 启动容器 → 输出全部入口与凭据。

`container` 模式下还会写入 `[webui].autostart_bot = true`：本体镜像的入口就是 WebUI，Bot 进程由它托管，不自动拉起的话容器虽然 running 但机器人并没有在跑。

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
| `--port KEY=PORT` | 覆盖**宿主机发布端口**（容器内监听端口固定，无需也无法改），可重复；`KEY` 见 `uv run deploy up --help` |
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
├── lxmusic2api/{config.toml,.private/,data/,downloads/}
├── napcat/ws.json  # 覆盖镜像模板的正向 WS 配置（含端口与令牌）
├── napcat/config/  # NapCat 自己的 onebot11.json / onebot11_<QQ>.json / webui.json
├── napcat/qq/      # QQ 登录态
├── backup/config_<时间戳>.toml
├── data/           # 挂给本体的 /data/Undefined/data
└── logs/           # 挂给本体的 /data/Undefined/logs
```

**幂等与凭据**：`up` 每次都会重新渲染 compose 与配置，但凭据一律优先复用已生效的值、最后才随机生成，因此重跑不会把 NapCat token、SearXNG `secret_key`、lxmusic2api key、WebUI 密码、Runtime `auth_key` 换掉。`changeme` 一类占位值会被替换，**且占位值不会挡住下一个来源**。

> 取值顺序分两类：
> - `[webui].password` 与 `[api].auth_key`：**`config.toml` 已生效的值 → `deploy/.env` → 随机生成**。这两个键是本体自己读的，`.env` 只是留档；以 config.toml 为准才不会因为一份过期的 `.env` 把用户手改过的密码改回去。
> - NapCat token、SearXNG `secret_key`、Firecrawl 与 lxmusic2api 的凭据：只认 `deploy/.env`——它给出的就是那些容器实际拿到的值，一旦被换掉，容器里的配置也得跟着换。
>
> 同理，**不要手工编辑 `deploy/.env` 里的端口与绑定地址**：端口和 `*_BIND` 优先从 `STATE.json` 读回，手改会在下一次 `up` 被覆盖。要改就用 `--port` / `--port-bind`。

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

`container` 模式下本体容器以 `/data/Undefined` 为工作目录，**整个仓库目录**都挂进这个路径，`deploy/data` 与 `deploy/logs` 再分别嵌套挂到 `data/`、`logs/`，`res/`、`img/` 以只读方式覆盖同名目录。所以在宿主机上直接编辑 `config.toml` 就生效，也不会覆盖镜像内的 Python 环境。

> 挂目录而不是单挂 `config.toml` 是有意的：`up` 写配置走「临时文件 + `os.replace`」原子替换，替换后 inode 变了，而单文件 bind mount 绑的是挂载那一刻的 inode——容器会一直读旧内容（compose 也不会因为文件内容变化而重建容器），于是轮换 token 或改 `ws_url` 之后本体仍用旧配置。也不要把父目录挂成只读：WebUI 的配置保存是原地写 `config.toml`，只读会直接失败。

---

## 4. 各服务说明

### NapCat（必需）

- 官方镜像 `mlikiowa/napcat-docker`，`MODE=ws`：NapCat 作为**正向 WebSocket 服务端**监听 3001，本体作为客户端连过去。
- WebUI 默认 6099，token 由脚本生成并通过 `NAPCAT_WEBUI_SECRET_KEY` 预设，**不需要进容器翻 token**；入口形如 `http://127.0.0.1:6099/webui?token=<token>`。
- 正向 WS 配置由脚本生成 `deploy/napcat/ws.json`（含 WebSocket 端口与访问令牌），
  以只读方式挂载覆盖镜像内的 `/app/templates/ws.json`。镜像入口每次**容器启动**都会把
  该模板拷成 `onebot11.json`，所以令牌不会像「启动后补写宿主文件」那样被下一次启动抹掉
  （那种做法同时也不安全：token 为空时 NapCat 不校验任何客户端）。
- 首次使用需要在 WebUI 里扫码登录，或直接看容器日志里的二维码：

```bash
docker logs -f napcat
```

- **未登录时协议端不会监听 3001**，此时本体连不上是正常现象。
- **登录之后 `onebot11.json` 就不再是生效文件**：NapCat core 优先读账号级的
  `deploy/napcat/config/onebot11_<QQ>.json`，而且它没有 fs.watch（热重载只走 WebUI
  通道）。此时模板里的 token/端口对该账号无效，`up` 的输出会点名这个文件。要让它
  重新对齐就删掉账号级文件并重启 napcat（`uv run deploy down && uv run deploy up`），
  或者直接在 NapCat WebUI 里核对网络配置。
- 模板只在容器启动时被读取一次：改端口或轮换 token 后需要重启 napcat 容器才会生效。

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

> `deploy/searxng` 是 bind mount，而镜像入口默认会 `chown -R searxng:searxng /etc/searxng`；一旦被 chown 成 `977:977`，非 root 的调用者就再也写不进去，第二次 `up` 重写 `settings.yml` 会直接 EACCES。因此 compose 里显式设了 `FORCE_OWNERSHIP=false`——容器本身以 root 运行（镜像没有 `USER` 指令），脚本原子写入的 `settings.yml` 是 `0600`（`tempfile.mkstemp` 的权限，`write_text` 只会在 `secret=True` 时额外 chmod，非敏感文件同样是 `0600`）、属主是调用者，root 读它没有问题，不需要那次 chown。代价是容器日志里会有一行关于属主的 WARNING，可以忽略。

### Firecrawl（`--with firecrawl`）

`firecrawl_search` 工具的后端。复用上游 GHCR 预构建镜像，会拉起 **5 个容器**：`firecrawl-api`、`firecrawl-playwright`、`firecrawl-redis`、`firecrawl-rabbitmq`、`firecrawl-postgres`。

- 上游 compose 默认走本地 `build:`，我们改用官方预构建镜像；同时补上上游缺失的持久化卷（Postgres 存 NuQ 队列状态，Redis/RabbitMQ 存限流与消息）。
- `USE_DB_AUTHENTICATION=false` 时 Firecrawl **完全不校验 API Key**，因此 `[search.firecrawl].api_key` 随便填即可。这是官方行为，适用于可信网络，**不要把无鉴权的 API 暴露到不可信网络**。
- 资源占用较高（上游给 api 设 4 CPU / 8G、playwright 设 2 CPU / 4G，官方声明这不是最低要求），可按机器情况调整 `deploy/compose.yaml` 里 `firecrawl-api` 的 `cpus` / `mem_limit`（改完重跑 `up` 会按模板重新生成，长期调整请改模板）。
- 生成的 `firecrawl/.env` **不设置** `NUQ_BACKEND`：上游把它声明成 `z.enum(["pg","fdb"])` 并在启动时校验，写 `postgres` 会让 api 容器直接抛 Zod 错误起不来；留空即默认 pg 后端。
- **自托管 Firecrawl 没有 dashboard / playground**，唯一的管理界面是 Bull Board 队列页：`http://127.0.0.1:3002/admin/<BULL_AUTH_KEY>/queues`（`BULL_AUTH_KEY` 见 `deploy/firecrawl/.env`）。

### lxmusic2api（`--with lxmusic2api`）

`music.*` 工具集的后端。**上游没有任何预构建镜像**（仓库无 `.github`、无 tag、无 release），因此镜像由本项目在 CI 里 clone 上游固定 commit 后构建，推送到 `ghcr.io/<owner>/undefined-lxmusic2api:<短sha>`。

- 脚本生成的 `deploy/lxmusic2api/config.toml` 含三项必需配置：`server.host = "0.0.0.0"`、`legal.accept_lx_music_terms = true`、随机且长度 ≥32 的 `auth.api_key`。缺任一项上游会拒绝启动。
- `deploy/lxmusic2api/{data,downloads}` 由脚本预先创建：这两个目录是 bind mount 源，交给 dockerd 建会变成 root:root，而服务以调用者 uid 运行，连 sqlite 都写不了。
- **取音频直链需要自备 LX 自定义音源脚本**：把兼容「LX 自定义源 API v2」的 `.js` 放到 `deploy/lxmusic2api/.private/custom-source.js`（或改用目录模式），然后重启该容器。没有音源时服务仍会启动，搜索/歌单/歌词可用，但取音频直链会返回 503，`up` 的输出里也会明确提示。
- 唯一浏览器界面是只读的 Swagger 文档：`http://127.0.0.1:3000/docs`。
- 上游许可证为 Apache-2.0 附加 LX Music 补充协议（仅技术学习/非商业、版权数据 24 小时内清除、须自行确认音源合法性），使用前请阅读上游 `LICENSE` 与 `LICENSES/`。

### NagaAgent（`--with-nagaagent`）

NagaAgent 是仓库的 git submodule（`code/NagaAgent`），不是独立服务。选择拉取后：

- 脚本检查子模块是否已初始化，未就绪时执行 `git submodule update --init --recursive code/NagaAgent`；失败会中止并给出可手动执行的命令（不会静默继续）。
- 写入 `[features].nagaagent_mode_enabled = true`，即启用 NagaAgent 专用系统提示词与 `naga_code_analysis_agent`（该 Agent 的四个工具把 `base_path` 固定在 `Path.cwd()/code/NagaAgent`，所以能力开关与子模块存在性绑定）。
- **`[naga]` 整节都不碰**：`enabled` / `api_url` / `api_key` / `mode` / `use_proxy` / `moderation_enabled` 描述的是「怎么连你自己的 Naga 服务端」，脚本既没有部署它也无从得知地址与密钥，所以既不打开、也不清空。要对接 Naga 服务端请自己填这些字段。
- `container` 模式下 `code/NagaAgent` 会以只读方式挂进本体容器同一路径（`/data/Undefined/code/NagaAgent`），因此 `naga_code_analysis_agent` 的工具在容器里也能定位到目标代码。

不选择时只把 `[features].nagaagent_mode_enabled` 写成 `false`，相关提示词、Agent、命令与 API 端点全部隐藏。
**`[naga]` 下你自己填过的网关配置一律原样保留**——包括 `enabled = true`：默认部署不替你把已经接好的网关关掉。

---

## 5. 部署脚本会改哪些配置

`up` 只改**服务拓扑相关**的键，**取值不会被动到**（只替换目标键的当前值）。

> ⚠️ 渲染语义：输出会按 `config.toml.example` 的键序与注释映射**整份重排**。键上方能识别的
> `# zh:` / `# en:` 注释块会保留，但双语块里没有 `zh:`/`en:` 前缀的续行、以及不依附任何键的
> 独立说明块会丢失，键之间的空行会被规整（取决于原文件本身，可能少几行注释）。
> 你自己的键值不会丢，写盘前也会先备份，但首次对已有 `config.toml` 跑 `up` 时请留意 diff。

将要写入的键：

| 键 | 说明 |
|---|---|
| `[onebot].ws_url` | 按模式写入 `ws://napcat:3001` 或 `ws://127.0.0.1:3001` |
| `[onebot].token` | 与 NapCat 正向 WS 服务端一致的访问令牌（自动生成） |
| `[onebot].file_send_mode` / `file_send_host` | `container` 模式写入 `url` / `undefined-bot`（协议端按 compose 服务名访问本体 Runtime） |
| `[webui].url` / `[webui].password` | 监听地址按模式；密码为空或 `changeme` 时生成随机值 |
| `[api].host` / `[api].auth_key` | 同上 |
| `[webui].port` / `[api].port` | 容器内监听端口（与 compose 映射的目标端一致，宿主端口由 `--port` 决定） |
| `[webui].autostart_bot` | `container` 模式写入 `true`：镜像入口是 WebUI，Bot 进程由它托管 |
| `[features].nagaagent_mode_enabled` | 见上一节 |
| `[search].searxng_url` | 选了 SearXNG 时写入 |
| `[search].firecrawl_search_enabled` / `[search.firecrawl].base_url` | 选了 Firecrawl 时写入 |
| `[lxmusic2api].base_url` / `.api_key` | 选了 lxmusic2api 时写入 |

**不会碰**：`[models.*]`（模型端与 API Key 需要你自己填）、`[access]`、`[prompt]`、`[history]` 等。

`config.toml` 不存在时会先从 `config.toml.example` 复制一份完整配置，再在其上做最小差异修改——
这样生成出来的文件包含 `[models]` / `[core]` 等所有段落，你照着填即可（而不是只有被改的那几个键）。

写盘前会先把原文件备份到 `deploy/backup/config_<UTC 时间戳>.toml`；解析失败时直接中止且不写任何文件。`--dry-run` 连备份都不写。

---

## 6. 镜像与 CI

发布镜像在 `v*` tag 推送时由 `.github/workflows/release.yml` 构建：`build-docker`（按架构分别推送 digest）→ `merge-docker`（合并 manifest）→ `publish-release` → `publish-pypi`。该 workflow **只有 tag 推送触发**，没有 `workflow_dispatch`；已经打过 tag 的旧版本不会补建镜像，`v3.16.1` 及更早的版本需要本地构建（见下方）。

| 镜像 | 内容 |
|---|---|
| `ghcr.io/<owner>/undefined-bot:<tag>` | 本体：Python 3.12 + 依赖 + ffmpeg + docker CLI + Playwright Chromium |
| `ghcr.io/<owner>/undefined-lxmusic2api:<短sha>` | lxmusic2api，clone 上游 pin 的 commit 后构建 |

两者都构建 `linux/amd64` 与 `linux/arm64`：两个架构分别在原生 runner（`ubuntu-24.04` / `ubuntu-24.04-arm`）上按 digest 推送，再由 `merge-docker` 合并成 manifest list。arm64 runner 对公共仓库免费，私有仓库需要相应套餐。推送使用内置 `GITHUB_TOKEN`（workflow 已声明 `packages: write`），**不需要额外配置 secret**。

> **GHCR 包首次推送默认为 private。** 拉取前需要 `docker login ghcr.io`，或者到 GitHub 的包设置里把可见性改成 public，否则 `up` 拉镜像会 401。
>
> 从源码部署时也可以完全不用预构建镜像，改为本地构建：
> `docker build -f src/Undefined/deploy/templates/Dockerfile.bot -t ghcr.io/<owner>/undefined-bot:v<版本> .`

**升级 lxmusic2api 上游**：改 `src/Undefined/deploy/images.py` 里的 `LXMUSIC2API_UPSTREAM_SHA`，然后打下一个 tag。pin 必须是完整 commit sha——`tests/test_deploy_catalog.py` 会强制这一点（上游没有 tag/release，短 sha 会被当作镜像 tag，只有完整 sha 才能复现构建）。因此 CI 无条件构建该镜像；`uv run deploy` 也只在真的选中 lxmusic2api 时才解析它。

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

**改端口**：`uv run deploy up --port napcat_ws=13001 --port bot_webui=18787`。这里给的是**宿主机端口**：
compose 会写成 `${绑定地址}:${你的端口}:<容器内固定端口>`，同时把 `[webui].port` / `[api].port`
同步成容器内端口，因此应用监听、端口映射、`[onebot].ws_url` 三者始终一致。
端口与绑定地址会和凭据一样**跨次保留**（记在 `deploy/STATE.json` 与 `.env`），不带参数重跑不会退回默认值。

**远程访问**：默认所有端口只绑 `127.0.0.1`。要远程访问用 `--port-bind 0.0.0.0`（**不要**手改 `.env` 里的 `*_BIND`，那个值会被 `STATE.json` 覆盖掉），但请注意 Undefined WebUI、NapCat WebUI、Firecrawl API 都不是为公网暴露设计的，请自行加防火墙或反向代理。

**更新镜像**：`uv run deploy up --pull always`（会检查每个 tag 的更新；pin 的 tag 内容不变时不会产生变化）。

---

## 8. Docker 访问方式（DooD）

`container` 模式下本体容器挂载宿主机的 `/var/run/docker.sock`，即 **DooD（Docker-out-of-Docker）**：`python_interpreter` 与 `code_delivery_agent` 通过宿主 daemon 启动兄弟容器，不额外跑一个 `dockerd`。

- 优点：资源开销几乎为零，不需要 `privileged`，`python_interpreter` 的 `--network none` 隔离照常生效。
- 代价：能看到并能操作宿主机上的**全部容器**，权限等级等同于宿主机 root。这两个工具本身的设计就是「让模型在沙箱容器里执行代码」，但 `--network none` 只隔离网络，不是权限隔离；只应部署在你自己可控的机器上。
- 若不想给这个能力：`deploy/compose.yaml` 每次 `up` 都会重写，所以手改那一行不会保留。可行做法是改用 `host` 模式部署本体，或自己基于生成的 compose 起容器并维护它。代价是 `python_interpreter` / `code_delivery_agent` 会以「找不到 docker 命令」失败（属预期行为）。
- 加固：本体容器设了 `security_opt: no-new-privileges:true`（挡掉 setuid/setgid 提权路径）。这不会影响容器内的 Playwright——Chromium 只在显式传 `chromiumSandbox: true` 时才启用自带沙箱，否则 Playwright 自己会加 `--no-sandbox`。除此之外没有更多加固空间：容器以 root 运行且必须能操作宿主 docker daemon。
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
| `up` 之后容器在跑但机器人没反应 | `container` 模式下 Bot 由容器内 WebUI 托管、部署脚本会写 `[webui].autostart_bot = true`；若被改回 `false`，去 WebUI 点「启动机器人」或改回该键 |
| `up` 失败后 `down`/`status` 能跑但信息不全 | `STATE.json` 缺失只降级为提示（按默认项目名继续）；重跑一次 `up` 就会补齐 |
| 日志 / 数据目录属主是 root | 本体容器以 root 运行，`deploy/{data,logs}` 里的文件属 root；`--purge` 因此可能删不掉，需要 `sudo rm -rf`（脚本会列出残留项） |
| 收到的语音等本地文件读不到 | 已知限制：`container` 模式下协议端与本体不在同一文件系统，NapCat 对「没有 URL、只能给本地路径」的文件（典型是 silk 语音）给出的是**它容器内**的路径，本体读不到。`enableLocalFile2Url` 与 NapCat 自带 HTTP 端口的行为尚未在真机验证，因此生成的 `ws.json` 保持 `httpServers: []`、`enableLocalFile2Url: false` 不猜；需要这类能力时请自行在 NapCat WebUI 里开启并实测 |
| `config.toml` 被改错 | 从 `deploy/backup/` 取最近一份备份覆盖回去 |

---

## 10. 当前范围之外

- 远程（SSH）部署：脚本只在目标机本机执行。
- 反向代理 / HTTPS / 证书：自行在 Docker 前面加。
- Windows / macOS 适配：脚本按 Linux 编写（uid/gid、`/var/run/docker.sock` 等）。
- 微信 iLink 的容器编排：仍按 [配置说明](configuration.md) 在宿主机或容器内自行启用。
- Firecrawl 的 LLM 相关可选功能（`OPENAI_API_KEY` 等）：默认不预设，需要时写进 `deploy/firecrawl/.env`。
- 不代填模型配置：部署完成后仍需在 `config.toml` 的 `[models.*]` 里填模型端与 API Key，Bot 才能真正收发消息。
