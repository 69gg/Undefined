# Docker 一键部署

> 部署方式推荐顺序：[源码部署（首选）](deployment.md#源码部署推荐) → **Docker 一键部署（本文）** → [pip / uv tool 安装](deployment.md#pipuv-tool-部署快速体验)。

在 Linux 上，用一条命令部署 **Undefined + NapCat**，并按需添加搜索、音乐服务。部署工具会连接好各服务、生成访问密码，并在修改已有配置前自动备份。

**第一次部署按下面的顺序操作即可：准备环境 → 执行部署 → 填写模型与 QQ 配置 → 扫码登录 → 在 WebUI 启动 Bot → 测试回复。** 默认不安装 SearXNG、Firecrawl、lxmusic2api，也不启用 NagaAgent 问答；需要时可以再添加。

[首次部署](#1-开始前的准备) · [配置与登录](#3-完成配置并登录-qq) · [可选服务](#4-按需添加功能) · [日常管理](#5-日常管理) · [常见问题](#7-常见问题)

## 1. 开始前的准备

请在准备运行机器人的 Linux 电脑或服务器上操作，并准备好：

- **Docker Engine 和 Compose 插件**：需要能执行 `docker compose`（v2 或更新版本），且当前用户有权限连接 Docker。安装方法见 [Docker Engine 官方指南](https://docs.docker.com/engine/install/) 和 [Compose 插件安装指南](https://docs.docker.com/compose/install/linux/)。
- **Git**：用于下载项目。
- **uv**：用于运行部署命令。未安装时，按 [uv 官方安装指南](https://docs.astral.sh/uv/getting-started/installation/)安装；Linux 可执行下方命令，完成后按安装提示重新打开终端。
- **模型服务和 QQ 帐号**：准备模型 API 地址、API Key、模型名称，以及机器人的 QQ 号和管理员 QQ 号，部署后会用到。

```bash
# 仅在尚未安装 uv 时执行
curl -LsSf https://astral.sh/uv/install.sh | sh
```

部署前可检查工具是否就绪：

```bash
uv --version
git --version
docker compose version
docker info
```

`docker info` 应能正常返回服务信息。Python 环境由 uv 按项目要求准备；默认容器模式的镜像已包含 Bot 所需的 Python 依赖、FFmpeg 和 Playwright Chromium。

> 目前一键部署面向 Linux。Windows / macOS 用户请先按 [源码部署指南](deployment.md#源码部署推荐)安装。

## 2. 执行一键部署

首次下载项目并启动向导：

```bash
git clone https://github.com/69gg/Undefined.git
cd Undefined
uv run deploy up
```

已有仓库时，直接进入仓库根目录执行 `uv run deploy up`。不必预先创建 `config.toml`，缺少时会自动从示例生成。

首次使用可以按下表选择：

| 向导选项 | 第一次部署怎么选 |
|---|---|
| 本体部署方式 | 保持默认 `container`，让 Undefined 和 NapCat 一起在 Docker 中运行 |
| 额外部署哪些自托管服务 | 可先看[各服务的用途与选择建议](#4-按需添加功能)；暂时不需要就直接回车，之后可以再添加 |
| 发布端口的绑定地址 | 保持 `127.0.0.1`；在服务器上部署时，访问方法见下文[远程访问](#在自己的电脑上访问服务器) |
| 是否拉取 NagaAgent 子模块 | 不需要 NagaAgent 代码问答时选“否” |

向导随后会展示配置变更，确认后开始拉取镜像和启动容器。首次运行需要下载依赖与镜像，请等待命令完成。

如需跳过向导，可用 `uv run deploy up --yes` 代替；首次执行采用默认配置，之后执行会沿用上次的部署选择。只想提前查看变更时，可用 `uv run deploy up --dry-run`，它不会写文件或启动容器。

## 3. 完成配置并登录 QQ

部署结束后，终端会显示服务入口、WebUI 密码和带 token 的 NapCat 登录链接。没有记下时，在仓库目录重新执行：

```bash
uv run deploy status
```

默认入口如下；修改过端口时，以终端输出为准。

| 入口 | 默认地址 | 用途 |
|---|---|---|
| Undefined WebUI | `http://127.0.0.1:8787` | 填写配置、管理 Bot、查看日志 |
| NapCat WebUI | `http://127.0.0.1:6099/webui` | 使用终端给出的带 token 链接进入，扫码登录 QQ |
| Runtime API | `http://127.0.0.1:8788` | Bot 启动后供 Chat 等客户端连接，凭据为终端显示的 `auth_key` |

> 如果命令是在远程服务器上运行的，浏览器中的 `127.0.0.1` 指向你自己的电脑。请先按下面的[远程访问说明](#在自己的电脑上访问服务器)连接，再继续配置。

### 填写机器人与模型配置

1. 打开 Undefined WebUI，使用部署输出中的密码登录。
2. 在配置管理中填写 `core.bot_qq`（机器人 QQ 号）和 `core.superadmin_qq`（你的管理员 QQ 号）。
3. 配置 `models.chat`、`models.vision`、`models.agent` 的 API 地址、API Key 和模型名称；其他已启用功能所需的模型也应按配置提示填写。完整要求见 [配置必填项](configuration.md#3-严格模式stricttrue必填项)。
4. 保存配置并检查校验结果；字段缺失或无效时，按提示补齐。

也可以直接编辑仓库根目录的 `config.toml`。部署工具已填写 OneBot 连接和所选服务的地址，首次部署通常无需再改这些项。**模型 API 和 QQ 身份信息需要你自己填写，容器启动不代表这些配置已完成。**

### 扫码登录并测试回复

1. 打开终端显示的 NapCat WebUI 链接，扫描二维码，登录与 `core.bot_qq` 一致的 QQ 帐号。也可执行 `uv run deploy logs napcat --tail 200` 查看登录提示。
2. 返回 Undefined WebUI，点击“启动机器人”。部署工具会将 `[webui].autostart_bot` 设为 `false`，便于先完成配置与 QQ 登录；容器运行后 WebUI 会等待你手动启动 Bot。
3. 用另一个 QQ 私聊机器人，或在允许使用的群里 @ 机器人，发送一条简单消息，确认能收到回复。

NapCat 未登录时，Bot 日志提示连不上协议端属于正常现象。遇到问题可同时查看 NapCat 和 Bot 日志，操作说明见 [WebUI 使用指南](webui-guide.md)。

### 在自己的电脑上访问服务器

默认端口只允许部署机器本机访问。可在**你自己的电脑**上建立 SSH 隧道，将 WebUI 和 NapCat 管理页面转发过来：

```bash
ssh -N -L 8787:127.0.0.1:8787 -L 6099:127.0.0.1:6099 用户名@服务器地址
```

将 `用户名@服务器地址` 替换成你的 SSH 登录信息，保持该终端打开，然后访问上表中的本机地址。修改过端口时，相应调整转发端口。

在 **`container` 模式**下，需要通过服务器 IP 直接访问时，可以重新部署并设置 Docker 发布端口的绑定地址：

```bash
uv run deploy up --port-bind 0.0.0.0
```

此选项会开放**所有已选 Docker 服务的发布端口**，请配合防火墙或反向代理限制访问范围，尤其不要把无鉴权的 Firecrawl API 直接暴露到公网。脚本不自动配置 HTTPS 或证书。

在 **`host` 模式**下，`--port-bind` 只影响 NapCat 等容器服务，不会让宿主机上的 Undefined WebUI 或 Runtime API 通过服务器 IP 可达；部署工具仍将 `[webui].url` 和 `[api].host` 设为 `127.0.0.1`。可继续使用上面的 SSH 隧道；如需直接访问本体，须在部署完成后单独修改这两项监听地址，并重启对应的 WebUI / Bot 进程。再次运行部署工具会将这两项恢复为回环地址。

## 4. 按需添加功能

**NapCat 随一键部署安装，是收发 QQ 消息的必需服务。** SearXNG、Firecrawl、lxmusic2api 都是可选项；第一次可以只部署 Undefined + NapCat，之后再按需要添加。

| 服务 | 用来做什么 | 什么时候需要 |
|---|---|---|
| NapCat | 登录 QQ、收发消息与文件，连接 Undefined 和 QQ | 使用 QQ 机器人必需，自动安装 |
| SearXNG | 聚合多个搜索引擎，为 `web_search` 提供搜索结果 | 希望使用 `web_search`，且没有可连接的 SearXNG 实例时 |
| Firecrawl | 为 `firecrawl_search` 提供自行托管的搜索接口 | 希望自己运行 Firecrawl 时；**不自部署也能使用官方 keyless** |
| lxmusic2api | 为 `music.*` 提供歌曲搜索、歌单、歌词与音频获取 | 需要音乐功能，且没有可连接的 lxmusic2api 实例时 |

根据需要在向导中选择，或使用 `--with` 一次列出要部署的可选服务：

```bash
# 部署 SearXNG 搜索服务
uv run deploy up --with searxng

# 同时部署 SearXNG 和音乐服务
uv run deploy up --with searxng,lxmusic2api
```

**`--with` 指定的是本次完整的可选服务列表。** 已部署其他可选服务并希望保留时，请一并列出；不传这个参数会沿用上次选择，`--with ""` 表示取消所有可选服务。

### NapCat：连接 QQ

Undefined 负责理解消息和执行工具，NapCat 负责登录 QQ 并实际收发消息。部署工具会配置好两者的 WebSocket 连接和访问令牌，你只需在部署后扫码登录机器人帐号。默认管理入口是 `http://127.0.0.1:6099/webui`，请使用终端显示的带 token 链接进入。

NapCat 必需，不用在 `--with` 中填写。没有登录 QQ 时，Bot 无法正常收发 QQ 消息；首次登录步骤见[配置与登录](#3-完成配置并登录-qq)。

### SearXNG：聚合网页搜索

SearXNG 为 `web_agent` 中的 `web_search` 工具提供搜索结果，适合希望自己运行搜索服务的用户。选中后会自动开启 JSON 搜索接口，并写入 `[search].searxng_url`；默认浏览器入口是 `http://127.0.0.1:8080/`。

已有可用实例时，可直接在配置中填写它的地址，无需重复部署。未部署且未配置可用地址时，`web_search` 不可用；`grok_search`、`firecrawl_search` 和网页读取工具不受此选项影响，按各自配置使用。

### Firecrawl：官方 keyless 或自托管搜索

**不部署 Firecrawl 容器，不影响 `firecrawl_search` 工具使用官方服务。** 只想使用搜索工具时，可以不勾选 Firecrawl，在 WebUI 的搜索配置中开启该工具、保留官方地址，并将 API Key 留空，即使用官方 keyless。对应 `config.toml` 中的字段如下（修改已有段落即可）：

```toml
[search]
firecrawl_search_enabled = true

[search.firecrawl]
base_url = "https://api.firecrawl.dev"
api_key = ""
```

工具默认关闭，需要先将 `firecrawl_search_enabled` 设为 `true`。Keyless 无需 API Key，但受官方按 IP 计算的每日请求与额度限制；需要更高额度时可填写自己的 API Key，详见 [Firecrawl 官方限流说明](https://docs.firecrawl.dev/rate-limits#keyless-no-api-key)。未选自托管 Firecrawl 时，部署工具会保留已有的 Firecrawl 配置；如果之前使用本地实例，切回官方服务时也要将 `base_url` 改回上面的地址。

希望自行托管时，在向导中选择 Firecrawl，或将 `firecrawl` 加入 `--with` 列表。部署工具会开启 `firecrawl_search` 并将其指向本地实例。它会启动 API、浏览器处理服务、Redis、RabbitMQ、PostgreSQL 共 5 个容器，占用的资源较多，适合愿意自行维护服务的用户。

自托管实例的默认 API 端口为 `3002`；终端会给出队列管理页，没有独立的 dashboard / playground。搜索效果取决于实例的搜索后端与网络环境，具体设置见 [Firecrawl 自托管说明](https://docs.firecrawl.dev/contributing/self-host)；同时选择 SearXNG 时，部署工具也不会自动将其设为 Firecrawl 的搜索后端。

### lxmusic2api：音乐搜索与音频获取

lxmusic2api 为 `music.*` 工具提供歌曲搜索、歌单浏览、歌词和音频获取。选中后会自动设置 `[lxmusic2api]` 的服务地址与访问密钥；默认接口文档为 `http://127.0.0.1:3000/docs`。已有服务时，也可自行填写地址和密钥，无需重复部署。

不配置音乐服务时，`music.*` 工具不可用，其余聊天与工具功能可正常使用。搜索、歌单和歌词不需要音源脚本；获取音频还需完成下面的配置。

#### 音乐服务的音源配置

将兼容“LX 自定义源 API v2”的 `.js` 脚本放到：

```text
deploy/lxmusic2api/.private/custom-source.js
```

然后在仓库根目录执行：

```bash
docker compose --env-file deploy/.env -f deploy/compose.yaml restart lxmusic2api
```

没有音源脚本时，搜索、歌单和歌词功能仍可使用，但获取音频直链会返回 503。使用前请阅读 [lxmusic2api 上游项目](https://github.com/69gg/lxmusic2api)的许可证与 LX Music 补充协议；部署工具会设置接受 LX Music 条款的配置项。

### NagaAgent 代码问答

需要让机器人回答 NagaAgent 代码相关问题时，使用：

```bash
uv run deploy up --with-nagaagent
```

这会拉取 `code/NagaAgent` 子模块并启用代码问答能力。它不会部署 Naga 服务端；已有 `[naga]` 网关配置会保留，服务端接入请按 [Naga 配置说明](configuration.md#428-naga-naga-外部网关集成)另行设置。

## 5. 日常管理

以下命令均在仓库根目录执行：

```bash
uv run deploy status                              # 查看状态、入口与部署凭据
uv run deploy logs                                # 持续查看所有服务日志
uv run deploy logs undefined-bot napcat --tail 200  # 查看 Bot 与 NapCat 最近日志
uv run deploy down                                # 停止并移除容器，保留数据
uv run deploy up                                  # 按已有选择重新启动
```

查看日志时按 `Ctrl+C` 结束跟踪，不会停止服务。

### 修改端口和部署选择

端口冲突时，通过 `--port` 指定新的宿主机端口，例如：

```bash
uv run deploy up --port bot_webui=18787 --port napcat_webui=16099
```

修改后分别通过 `18787` 和 `16099` 访问两个管理页面。部署工具会记住端口与绑定地址，下次重跑无需重复填写；请通过命令参数修改，避免手工改 `deploy/.env` 或 `deploy/STATE.json`。

重新运行向导可以调整模式和可选服务。重复部署会重新生成 Compose 与服务配置，并复用已有有效凭据；对生成文件的手工修改可能被覆盖。修改过 WebUI 密码时，以 `config.toml` 中的当前值为准。

### 更新版本

先备份配置与数据，并将仓库更新到要部署的已发布版本，再执行：

```bash
uv run deploy up --pull always
```

部署工具会按当前仓库版本选择 Bot 镜像，并检查所用镜像的更新。只执行这条命令不会自动把仓库切换到新版本。需要本地构建或维护镜像时，参阅 [Docker 镜像构建与维护](build.md#docker-镜像构建与维护)。

### 数据保存与备份

| 位置 | 保存的内容 |
|---|---|
| `config.toml` | Bot 配置，包括你填写的模型 API 和 QQ 身份信息 |
| `config/`、`knowledge/` 及自行修改的 `res/`、`img/` | 自定义配置、知识库原始文件和资源 |
| `deploy/.env`、`deploy/STATE.json` | 部署凭据、所选服务、模式与端口 |
| `deploy/napcat/` | NapCat 配置与 QQ 登录状态 |
| `deploy/data/`、`deploy/logs/` | 容器模式下 Bot 的数据与日志；`host` 模式使用仓库根目录的 `data/`、`logs/` |
| `deploy/backup/` | 部署工具修改 `config.toml` 前的备份 |
| `deploy/searxng/`、`deploy/firecrawl/`、`deploy/lxmusic2api/` | 已选服务的配置，以及音乐服务的音源、数据和下载文件 |

备份时保存 `config.toml`、`deploy/` 和你使用的自定义目录。Firecrawl 等服务还使用 Docker 命名卷，备份这些服务时需另行备份对应卷；仅复制 `deploy/` 不能保存全部数据库数据。

普通停止使用 `uv run deploy down` 即可。**`down --volumes` 会删除 Compose 管理的数据卷；`down --purge` 还会删除整个 `deploy/`，包括登录态、凭据、配置备份和容器模式下的 Bot 数据，不可恢复。**

## 6. 其他部署方式与参数

### 让 Undefined 在宿主机运行

需要在宿主机调试或运行 Bot 时，选择 `host` 模式。NapCat 和可选服务仍由 Docker 管理，Undefined 需要另行启动：

```bash
uv run deploy up --mode host
uv run Undefined-webui
```

宿主机上的 Playwright、FFmpeg 等依赖按 [源码部署指南](deployment.md#源码部署推荐)准备。启动 WebUI 后，完成配置与 QQ 登录，再点击“启动机器人”。`host` 模式同样关闭 Bot 自动启动、使用 Stream 向 NapCat 发送文件，无需共享发送目录。`container` 与 `host` 模式使用不同的数据目录，切换模式不会自动迁移历史数据。

### 常用参数速查

| 参数 | 说明 |
|---|---|
| `--mode container\|host` | 选择 Bot 运行位置，首次默认 `container` |
| `--with searxng,firecrawl,lxmusic2api` | 设置完整的可选服务列表，按需删减；也可使用 `--with-searxng` 等独立参数 |
| `--with-nagaagent` / `--no-nagaagent` | 开启或关闭 NagaAgent 代码问答，首次默认关闭 |
| `--port KEY=PORT` | 修改宿主机发布端口，可重复使用；端口键见 `uv run deploy up --help` |
| `--port-bind ADDR` | 设置所有发布端口的绑定地址，首次默认 `127.0.0.1` |
| `--pull missing\|always\|never` | 镜像拉取策略，默认 `missing`；分别表示本地缺少时拉取、总是检查更新、不拉取 |
| `--dry-run` | 预览配置差异与 Compose，隐藏凭据，不写文件、不启动容器 |
| `--yes` / `-y` | 跳过向导，未指定项沿用上次选择或首次默认值 |

### 配置修改与运行权限

部署工具会更新 OneBot 连接、WebUI / Runtime 监听地址与凭据、Bot 启动方式、文件发送模式和所选服务地址；模型、访问控制、提示词和历史配置的取值会保留。已有配置在写入前会备份，但写回时可能调整排序、空行或部分注释，可先用 `--dry-run` 查看计划。

每次执行 `uv run deploy up`，`container` 与 `host` 模式都会写入 `webui.autostart_bot = false` 和 `onebot.file_send_mode = "stream"`。Bot 由你在 WebUI 中手动启动；本地文件通过已有 OneBot WebSocket 分块上传给 NapCat，无需共享发送目录，也不依赖 Runtime 提供下载地址。`file_send_host` 仅供 URL 模式使用，部署工具不再改写它。

Stream 只处理发送文件。对收到的仅含 NapCat 容器内路径的文件，仍存在读取限制，见下面的常见问题。

本体容器默认挂载宿主机 Docker socket，供 Python 代码执行和代码交付工具使用，因此具备控制宿主机 Docker 的权限，相当于宿主机 root 权限。请在自己可控的机器上部署；需要限制这项权限时，应自行维护 Compose 配置并评估相关工具的可用性。

## 7. 常见问题

| 遇到的情况 | 可以怎么处理 |
|---|---|
| 提示找不到 `uv`、`docker` 或 Compose 插件 | 按[环境准备](#1-开始前的准备)安装对应工具；`host` 模式也需要 Docker 来运行 NapCat 和可选服务 |
| `docker info` 无法连接或提示权限不足 | 确认 Docker 服务已启动，且当前执行部署命令的用户有访问权限 |
| WebUI 页面打不开 | 先用 `uv run deploy status` 看容器是否在运行、端口是否正确；远程服务器默认不能直接通过公网 IP 访问，按[远程访问说明](#在自己的电脑上访问服务器)连接 |
| WebUI 密码忘了 | 首次生成的密码可通过 `uv run deploy status` 查看；若之后改过密码，以 `config.toml` 的 `[webui].password` 为准 |
| Bot 日志提示连不上 `ws://napcat:3001` | 先到 NapCat WebUI 扫码登录；已登录仍失败时，核对 NapCat 的正向 WebSocket 配置和访问令牌是否与 Bot 一致 |
| 容器在运行，但机器人不回复 | 检查 QQ 登录状态、模型与 QQ 配置、WebUI 中的 Bot 状态，以及是否受访问控制限制；查看 `uv run deploy logs undefined-bot napcat --tail 200` 定位错误 |
| 修改 NapCat 令牌后仍无法连接 | 已登录帐号可能使用单独的网络配置。按部署输出提示，在 NapCat WebUI 中更新该帐号的正向 WebSocket 配置，保存并按提示重启 NapCat |
| `web_search` 提示未启用，或 SearXNG 返回 403 | 确认已选择 SearXNG；`deploy/searxng/settings.yml` 中的 `search.formats` 应包含 `json`。可重跑部署恢复生成配置；手工修改后，用 `docker compose --env-file deploy/.env -f deploy/compose.yaml restart searxng` 重启该服务 |
| Firecrawl 启动很慢或因内存不足退出 | 先检查 `uv run deploy logs firecrawl-api --tail 200`；可暂不自部署，按[官方 keyless 配置](#firecrawl官方-keyless-或自托管搜索)继续使用工具，或提供足够资源后再部署 |
| `music.get_audio` 返回 503 | 检查是否已按[音源配置](#音乐服务的音源配置)放入兼容的脚本并重启音乐服务 |
| 收到的语音等文件无法读取 | 某些消息只提供 NapCat 容器内的本地路径，Bot 无法直接读取。发送端的 Stream 模式不能解决这类接收问题；需按协议端实际能力提供可访问的 URL 或共享文件路径 |
| 部署中断后状态信息不完整 | 修复报错后重新执行 `uv run deploy up`，补齐部署状态和服务配置 |
| 清理数据时提示权限不足 | 部分文件由容器以 root 写入。根据命令列出的残留路径，确认不再需要后用具有权限的帐号清理 |
| 想恢复部署前的 Bot 配置 | 在 WebUI 中停止 Bot，将 `deploy/backup/` 中对应的备份恢复为仓库根目录的 `config.toml`，核对连接地址和凭据后再启动 |
