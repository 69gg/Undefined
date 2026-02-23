# 安装与部署指南

提供 pip/uv tool 安装与源码部署两种方式：前者适合直接使用；后者适合深度自定义与二次开发。

> Python 版本要求：`3.11`~`3.13`（包含）。
>
> 若使用 `uv`，通常不需要你手动限制系统 Python 版本；`uv` 会根据项目约束自动选择/下载兼容解释器。

---

## pip/uv tool 部署（快速，适合默认行为）

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

安装完成后，在任意目录准备 `config.toml` 并启动：

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

> `Undefined-webui` 会在检测到当前目录缺少 `config.toml` 时，自动从 `config.toml.example` 生成一份，便于直接在 WebUI 中修改。
> 提示：资源文件已随包发布，支持在非项目根目录启动；如需自定义内容，请参考下方说明。

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

因此你无需改动 site-packages，直接在运行目录放置覆盖文件即可，例如：

```bash
mkdir -p res/prompts
# 然后把你想改的提示词放到对应路径（文件名与目录层级保持一致）
```

如果你希望直接修改“默认提示词/默认文案”（而不是每个运行目录做覆盖），推荐使用下面的“源码部署”，在仓库里修改 `res/` 后运行；不建议直接修改已安装环境的 `site-packages/res`（升级会被覆盖）。

如果你不知道安装包内默认提示词文件在哪，可以用下面方式打印路径（用于复制一份出来改）：

```bash
python -c "from Undefined.utils.resources import resolve_resource_path; print(resolve_resource_path('res/prompts/undefined.xml'))"
```

资源加载自检（确保 wheel 资源可用）：

```bash
python -c "from Undefined.utils.resources import read_text_resource; print(len(read_text_resource('res/prompts/undefined.xml')))"
```

---

## 源码部署（推荐开发/高定使用）

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

### 3. 配置环境

复制示例配置文件 `config.toml.example` 为 `config.toml` 并填写你的配置信息。

```bash
cp config.toml.example config.toml
```

#### 源码部署的自定义指南

- **自定义提示词/预置文案**：直接修改仓库根目录的 `res/`（例如 `res/prompts/`）。
- **自定义图片资源**：修改 `img/` 下的对应文件（例如 `img/xlwy.jpg`）。
- **优先级**：若你希望“运行目录覆盖优先”：在启动目录放置 `./res/...`，会优先于默认资源生效（便于一套安装，多套运行配置）。

### 4. 启动运行

启动方式（二选一）：

```bash
# 1) 直接启动机器人（无 WebUI）
uv run Undefined

# 2) 启动 WebUI（在浏览器里编辑配置，并在 WebUI 内启停机器人）
uv run Undefined-webui
```

> **重要**：两种方式 **二选一即可**，不要同时运行。若你选择 `Undefined-webui`，请在 WebUI 中管理机器人进程的启停。

### 5. 跨平台与资源路径（重要）

- **资源读取**：运行时会优先从运行目录加载同名 `res/...` / `img/...`（便于覆盖），若不存在再使用安装包自带资源；并提供仓库结构兜底查找，因此从任意目录启动也能正常加载提示词与资源文案。
- **并发写入**：运行时会为 JSON/日志类文件使用“锁文件 + 原子替换”写入策略，Windows/Linux/macOS 行为一致（会生成 `*.lock` 文件）。
