# 安装与部署指南

提供源码部署与 pip/uv tool 安装两种方式：**源码部署是推荐的首选方式**，功能完整且经过充分测试；pip/uv tool 安装适合快速体验，但部分功能支持尚不完善。

> **Release 下载提示**：如果目的是部署 QQ Bot，不需要在 GitHub Release 的 Assets 中挑客户端安装包；按本文源码部署或 pip/uv tool 安装即可。Release 中的 `Undefined-Console-*` 和 `Undefined-Chat-*` 是可选客户端，选择说明见 [README — Release 下载速查](../README.md#release-下载速查)。
>
> **作为 Python 库嵌入**：若你不需要启动 QQ Bot CLI，而是要在自己的应用或测试中复用 Undefined 组件（配置、`AIClient`、Skills、认知记忆等），请参阅 [Python 库 API 参考](python-api.md) 与 [配置详解 — 库嵌入配置](configuration.md#2-库嵌入配置)。CLI 入口（`Undefined` / `Undefined-webui`）行为不受库嵌入 API 影响。
>
> Python 版本要求：`3.11`~`3.13`（包含）。
>
> 若使用 `uv`，通常不需要你手动限制系统 Python 版本；`uv` 会根据项目约束自动选择/下载兼容解释器。

---

## 源码部署（推荐）

### 1. 克隆项目

由于项目中使用了 `NagaAgent` 作为子模块，请使用以下命令克隆项目：

```bash
git clone --recursive https://github.com/69gg/Undefined.git
cd Undefined
```

如果已经克隆了项目但没有初始化子模块：

```bash
git submodule update --init --recursive
```

### 2. 安装依赖

推荐使用 `uv` 进行现代化的 Python 依赖管理（速度极快）：

```bash
# 安装 uv (如果尚未安装)
pip install uv

# 可选：预装一个兼容解释器（推荐 3.12）
# uv python install 3.12

# 同步依赖
# uv 会根据 pyproject.toml 自动处理 3.11~3.13 的解释器选择
uv sync
```

同时需要安装 Playwright 浏览器内核（用于网页浏览功能）：

```bash
uv run playwright install
```

### 3. 安装渲染运行时

网页截图和 Markdown 渲染依赖 Playwright 浏览器内核。源码部署时请执行：

```bash
uv run playwright install
```

`render.render_latex` 使用 Python 依赖中的 `matplotlib.mathtext` 在本地渲染常见数学公式，不需要额外安装系统 TeX，也不访问外部网络。复杂 TeX 环境和自定义宏可能不受支持，此时工具会立即返回明确错误。

`render.render_html` / `render.render_markdown` 的 `layout=long` 与普通渲染复用同一套 Playwright 运行时，无需新增系统依赖。渲染 BrowserContext 强制离线并终止全部网络请求；请将所需样式、脚本和图片内联，图片可使用 `data:` / `blob:` 资源。

如果 Playwright 自带 Chromium 未安装，渲染器会尝试复用系统已安装的 Chrome/Chromium。需要指定其他路径时，设置 `[render].browser_executable_path`；与 Playwright 自带版本相比，系统浏览器的版本兼容性不受 Playwright 保证，因此生产环境仍优先执行 `uv run playwright install`。

### 4. 配置环境

复制示例配置文件 `config.toml.example` 为 `config.toml` 并填写你的配置信息。

```bash
cp config.toml.example config.toml
```

#### 源码部署的自定义指南

- **局部扩展主提示词（推荐）**：使用 `[prompt.file_includes]` 把本地文件放入 P0/P1/P2/P3/summary 固定插槽，不需要修改受 Git 跟踪的主提示词。
- **完整覆盖提示词/预置文案**：需要替换整份资源时再修改仓库根目录的 `res/`（例如 `res/prompts/`）。
- **自定义图片资源**：修改 `img/` 下的对应文件（例如 `img/xlwy.jpg`）。
- **优先级**：若你希望“运行目录覆盖优先”：在启动目录放置 `./res/...`，会优先于默认资源生效（便于一套安装，多套运行配置）。

主 Prompt 局部扩展示例：

```bash
mkdir -p config/prompts
# 创建并编辑 config/prompts/identity.local.xml
```

```toml
[prompt.file_includes]
p0 = "config/prompts/identity.local.xml"
p1 = ""
p2 = ""
p3 = ""
summary = ""
```

源码仓库已忽略并从构建产物中排除 `config/prompts/*.local.*`。每次 AI 请求都会检查文件修改时间，未变化时复用缓存、变化时重新读取；配置路径修改后按现有配置热更新间隔生效。文件缺失或读取失败时会记录警告并跳过该插槽，不会阻止请求。完整配置与插槽位置见[配置说明](configuration.md#4112-promptfile_includes-主-prompt-本地文件插槽)。

> Git 与构建排除只防止私有文件被提交或打包；插入后的内容仍会作为 system Prompt 发送给模型供应商，不要在其中保存 API Key 等凭据。

### 5. 启动运行

启动方式（二选一）：

```bash
# 1) 直接启动机器人（无 WebUI）
uv run Undefined

# 2) 启动 WebUI（在浏览器里编辑配置，并在 WebUI 内启停机器人）
uv run Undefined-webui
```

> **重要**：两种方式 **二选一即可**，不要同时运行。若你选择 `Undefined-webui`，请在 WebUI 中管理机器人进程的启停。
>
> WebUI 功能详见 [WebUI 使用指南](webui-guide.md)。

#### 自动启动选项

若希望 WebUI 启动后自动拉起机器人进程，可在 `config.toml` 中设置：

```toml
[webui]
autostart_bot = true
```

这样运行 `uv run Undefined-webui` 时会自动启动 bot，无需手动操作。默认为 `false`。

### 6. 跨平台与资源路径（重要）

- **资源读取**：运行时会优先从运行目录加载同名 `res/...` / `img/...`（便于覆盖），若不存在再使用安装包自带资源；并提供仓库结构兜底查找，因此从任意目录启动也能正常加载提示词与资源文案。
- **并发写入**：运行时会为 JSON/日志类文件使用”锁文件 + 原子替换”写入策略，Windows/Linux/macOS 行为一致（会生成 `*.lock` 文件）。

### Management-first 推荐流程

推荐把 `Undefined-webui` 当作默认入口：

1. 运行 `uv run Undefined-webui`
2. 在浏览器中打开管理控制台
3. 若 `config.toml` 缺失，WebUI 会自动生成模板
4. 在控制台中补齐配置、保存并校验
5. 直接点击启动 Bot
6. 若需要远程管理，再使用桌面端或 Android App 连接到这个 Management API

这样可以避免"先手写配置、再反复命令行重启"的冷启动成本，尤其适合首次部署与远程运维。

---

## pip/uv tool 部署（快速体验）

> **注意**：pip/uv tool 安装方式的功能支持尚不如源码部署完善，也未经过充分测试。如遇问题，建议优先切换到源码部署。

适合只想“安装后直接跑”的场景，`Undefined`/`Undefined-webui` 命令会作为可执行入口安装到你的环境中。

```bash
# 方式 1：pip
pip install -U Undefined-bot
python -m playwright install

# 方式 2：uv tool（建议使用该方式进行隔离安装）
# 安装uv（若未安装）
pip install uv

# 可选：显式指定兼容解释器（不指定时 uv 也会自动选择）
# uv python install 3.12

uv tool install Undefined-bot
uv tool run --from Undefined-bot playwright install
```

> **渲染依赖提醒**：同源码部署要求一致，你需要在宿主机上预先安装 Playwright 浏览器内核。请参考上文 [3. 安装渲染运行时](#3-安装渲染运行时)。未配置前，HTML 与 Markdown 图片渲染可能会失败；LaTeX 常见公式使用本地 mathtext，不依赖浏览器。

安装完成后，在任意目录准备 `config.toml` 并启动（库嵌入场景也可用 `Config.from_mapping()` 代替配置文件，见 [python-api.md](python-api.md)）：

```bash
# 启动方式（二选一）
#
# 1) 直接启动机器人（无 WebUI）
Undefined
#
# 2) 启动 WebUI（在浏览器里编辑配置，并在 WebUI 内启停机器人）
Undefined-webui
```

> **重要提示**：`Undefined` 与 `Undefined-webui` **二选一即可**，不要同时运行两个进程；否则会出现“重复登录/重复收发消息”等问题。
>
> - 选择 `Undefined`：直接在终端运行机器人，修改 `config.toml` 后重启生效（或依赖热重载能力）。
> - 选择 `Undefined-webui`：启动后访问 WebUI（默认 `http://127.0.0.1:8787`，密码默认 `changeme`；**首次启动必须修改默认密码，默认密码不可登录**；可在 `config.toml` 的 `[webui]` 中修改），在 WebUI 中在线编辑/校验配置，并通过 WebUI 启动/停止机器人进程。
> - 若希望 `Undefined-webui` 启动后自动拉起机器人进程，可在 `config.toml` 的 `[webui]` 中设置 `autostart_bot = true`（默认 `false`）。

> `Undefined-webui` 会在检测到当前目录缺少 `config.toml` 时，自动从 `config.toml.example` 生成一份，便于直接在 WebUI 中修改。
> 提示：资源文件已随包发布，支持在非项目根目录启动；如需自定义内容，请参考上方源码部署的自定义指南。

### 完整日志（排查用）

如果你希望保留完整安装/运行日志，可直接重定向到文件：

```bash
# pip 安装日志
python -m pip install -U Undefined-bot 2>&1 | tee install.log

# 运行日志（CLI）
Undefined 2>&1 | tee undefined.log

# 运行日志（WebUI）
Undefined-webui 2>&1 | tee undefined-webui.log
```

### pip/uv tool 部署的自定义方式

wheel 会自带 `res/**` 与 `img/**`。为了便于自定义，程序读取资源文件时采用“可覆盖”策略：

1. 优先加载运行目录下的同名文件（例如 `./res/prompts/...`）
2. 若不存在，再使用安装包自带的资源文件

只需要局部补充主 Prompt 时，优先使用上文的 `[prompt.file_includes]`：它会在每次请求检查运行目录中的本地文件并在修改后重新读取，也不会复制整份默认 Prompt。

确实需要完整覆盖资源时，无需改动 site-packages，直接在运行目录放置覆盖文件即可，例如：

```bash
mkdir -p res/prompts
# 然后把你想改的提示词放到对应路径（文件名与目录层级保持一致）
```

完整资源覆盖在进程内会走资源缓存，修改后应重启 Bot。若希望直接修改“默认提示词/默认文案”（而不是每个运行目录做覆盖），推荐使用上面的“源码部署”，在仓库里修改 `res/` 后运行；不建议直接修改已安装环境的 `site-packages/res`（升级会被覆盖）。

如果你不知道安装包内默认提示词文件在哪，可以用下面方式打印路径（用于复制一份出来改）：

```bash
python -c "from Undefined.utils.resources import resolve_resource_path; print(resolve_resource_path('res/prompts/undefined.xml'))"
```

资源加载自检（确保 wheel 资源可用）：

```bash
python -c "from Undefined.utils.resources import read_text_resource; print(len(read_text_resource('res/prompts/undefined.xml')))"
```

---

## NapCat / Lagrange.Core 部署要求

Bot 本地文件支持三种发送方式，默认 `local`，保持旧部署的发送行为。**是否需要共享文件系统取决于模式**：

| 模式 | 共享文件系统 | 协议端要求 | Runtime 文件监听 |
|---|---|---|---|
| `local`（默认） | 必须按发送路径可见 | 能读取 Bot 给出的路径／`file://` URI | 不需要 |
| `url` | 不需要 | 对相应消息／文件接口支持 HTTP URL，且能访问 Runtime | 需要 |
| `stream` | 不需要 | 支持 NapCat `upload_file_stream` 扩展 | 不需要 |

```toml
[onebot]
file_send_mode = "local"
file_send_host = "127.0.0.1" # 仅 URL 模式使用，不包含协议、端口或路径
```

`local` 适用于同一宿主机、同一容器，或共享 volume 且内部路径一致的不同容器。协议端会在**自己的文件系统**中读取 URI；路径未挂载仍会报 `ENOENT`。

`url` 模式复用 `[api]` Runtime HTTP 服务，无需额外端口。`file_send_host` 填写协议端实际可达的 IPv4、IPv6 或域名；IPv6 会正确生成带方括号的 URL。端口取实际监听值，修改 `api.port` 而尚未重启时仍使用旧端口。默认 `127.0.0.1` 仅适用于协议端与 Bot 共用网络空间的情况，独立容器中的回环地址指向容器自身；需要同时保证 `[api].host` 的绑定允许协议端访问。Runtime 关闭或未就绪时准备阶段报错，不会自动启动服务。

URL 使用单文件独立令牌，有效期 16 分钟，支持 HEAD、Range 和重复读取。下载读取的是 Bot 保存的独立副本，业务删除源文件或切换模式不会影响有效链接。到期拒绝新请求，正在读取的请求可以完成，然后清理副本。不要在反向代理访问日志中记录文件 URL 查询串。

`stream` 通过已有 OneBot WebSocket 按 64 KiB 分块上传，每块单独等待确认，最后独立请求完成并校验路径、大小和 SHA-256，再发 QQ 消息。一个 Bot 的 Stream 文件投递串行，多文件顺序准备，文本消息不受上传锁影响。文件准备、发送和明确失败后的回退共用 8 分钟预算，排队等待不计时；协议端文件显式保留 16 分钟。未完成 Stream 失败时仅尝试重置该 Stream，已完成文件依靠保留期回收，不调用清空临时目录的接口。不支持零字节文件，不自动重试上传或跨重启续传。

**旧配置缺少新增字段且未通过环境变量指定模式时继续使用 `local`。** 需要跨文件系统发送时，可显式设置 `onebot.file_send_mode = "url"` 或 `"stream"`。选择 Stream 后，协议端明确不支持扩展时会提示切换配置，不会静默回退。NapCat 扩展不能视为所有 OneBot 实现的共同能力；使用 Lagrange.Core 等实现时应按其实际能力选 `local`，或核对所用消息与普通文件上传接口的 URL 支持后选择 `url`。

实现参考固定版本的 [NapCat 上传示例](https://github.com/NapNeko/NapCatQQ/blob/109d0c1dff755875f3b79795e99cee6115289fbb/packages/napcat-onebot/action/stream/test_upload_stream.py) 与 [UploadFileStream](https://github.com/NapNeko/NapCatQQ/blob/109d0c1dff755875f3b79795e99cee6115289fbb/packages/napcat-onebot/action/stream/UploadFileStream.ts)。Bot 新传输层使用分块 IO，但该上游在合并磁盘分块时仍构造完整内存缓冲区，现有附件登记也可能读取完整文件；**不承诺整个链路固定内存占用**。

### 受影响的功能

以下功能的本地来源统一经过该传输层，保留原始附件 UID、展示文件名与历史语义：

- `/stats` 统计图表
- `render.render_markdown` / `render.render_latex` 渲染图片
- 定时任务发送图片 / 音频
- `code_delivery_agent` 代码交付压缩包
- `messages.send_text_file` / `messages.send_url_file`
- Bilibili 视频下载发送

同时覆盖语音、视频缩略图和嵌套合并转发中的媒体，支持 CQ 字符串及消息段数组。已有 HTTP/HTTPS URL、Base64 或协议端资源标识原样通过。两项配置支持按投递快照热更新，见 [配置说明](configuration.md#43-onebot-协议端连接)。
