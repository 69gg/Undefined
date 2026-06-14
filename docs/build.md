# 构建指南

本文档说明 Undefined 当前仓库中的主要构建方式，包括：

- Python 包构建（`wheel` / `sdist`）
- `Undefined-webui` 管理控制台的本地开发与验证
- 跨平台连接器 `apps/undefined-console/` 的桌面端 / Android 构建
- 原生优先聊天客户端 `apps/undefined-chat/` 的桌面端 / Android 构建
- 手动 GitHub Actions artifact 构建
- GitHub Release 工作流的发布矩阵

> 约定：
>
> - 浏览器版管理入口仍然是 `uv run Undefined-webui`
> - 桌面端 / Android Console 是额外的连接器 / 容器，不替代 `Undefined-webui`
> - Undefined Chat 是 Runtime API 的原生聊天客户端，Runtime 仍是会话、历史、任务、附件和事件真源
> - Release 工作流默认覆盖 `Windows / macOS / Linux / Android`，不包含 `iOS`

## 1. 环境准备

### Python

- 推荐 Python：`3.12`
- 支持范围：`3.11` ~ `3.13`
- 推荐使用 `uv`

安装依赖：

```bash
uv sync --group dev -p 3.12
uv run playwright install
```

### LaTeX 渲染环境

`render.render_latex` 会优先使用 Python 依赖中的 `matplotlib` mathtext 在本地渲染常见数学公式，不需要额外安装系统 TeX。mathtext 无法处理的复杂内容会回退到 MathJax + Playwright，因此请确保已经执行：

```bash
uv run playwright install
```

如果运行环境无法访问 MathJax CDN，请在配置中启用 HTTP/HTTPS 代理，或尽量使用 mathtext 支持的常见数学公式语法。

### Node.js / Rust / Tauri

如果需要构建跨平台 Console 或 Chat，请额外准备：

- Node.js：建议 `22`
- Rust stable
- Tauri v2 所需系统依赖
- Android 构建时还需要 Java 17、Android SDK / NDK

## 2. Python 包构建

构建发行包：

```bash
uv build
```

仅构建 wheel：

```bash
uv build --wheel
```

常用本地校验：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests/
```

如果你修改了 `res/`、`img/`、`config.toml.example` 等打包资源，建议额外检查 wheel 内容是否齐全。

## 3. 浏览器版管理控制台

### 本地开发入口

推荐直接运行：

```bash
uv run Undefined-webui
```

这条命令会启动管理控制台。推荐工作流：

1. 启动 `Undefined-webui`
2. 在浏览器中打开 WebUI
3. 若 `config.toml` 缺失，先由 WebUI 自动生成模板
4. 在 WebUI 中补齐配置、保存并校验
5. 直接点击启动 Bot

### 说明

当前仓库中的 WebUI 静态资源直接由 Python 后端托管，不需要额外执行前端打包命令。

如果你修改了：

- `src/Undefined/webui/templates/`
- `src/Undefined/webui/static/js/`
- `src/Undefined/webui/static/css/`

建议至少运行：

```bash
uv run pytest tests/test_webui_management_api.py -q
uv run ruff check src/Undefined/webui
```

## 4. 跨平台 App

当前 App 的职责不是维护一套长期独立的第二后台，而是：

- 保存连接档案
- 使用一个 IP/域名 + 两个端口录入方式管理实例
- 测试 Management / Runtime 入口
- 自动尝试登录后打开真正的远程 WebUI
- 退出 WebUI 后回到主界面

跨平台 Console 位于：

```text
apps/undefined-console/
```

Undefined Chat 位于：

```text
apps/undefined-chat/
```

### 安装依赖

```bash
cd apps/undefined-console
npm install
```

Chat 使用同样的安装方式：

```bash
cd apps/undefined-chat
npm install
```

### Web 壳本地调试

```bash
npm run dev
```

### 桌面端调试

```bash
npm run tauri:dev
```

### 桌面端构建

```bash
npm run tauri:build
```

#### Linux 本地 AppImage 备注

在部分较新的 Linux 发行版上，本地执行 `npm run tauri:build` 可能在 AppImage 阶段失败，常见表现是：

- `failed to run linuxdeploy`
- 或 `strip` 无法处理 `.relr.dyn` 段

如果你本地遇到这个问题，可直接使用：

```bash
NO_STRIP=true npm run tauri:build
```

或者使用仓库里补好的快捷脚本：

```bash
npm run tauri:build:no-strip
```

如果你只想在本机先验证 Linux 安装包链路，也可以优先只打 `deb`：

```bash
npm run tauri:build:no-strip -- --bundles deb
```

这个问题主要是本机 `linuxdeploy` / `strip` 工具链兼容性导致，不一定代表项目代码或 Tauri 配置有问题。

### Android 初始化与构建

首次或 CI 环境中，先初始化 Android 项目：

```bash
npm run tauri:android:init
```

Undefined Chat 的 `tauri:android:init` 会在 Tauri 生成 `src-tauri/gen/android` 后自动运行 `scripts/prepare_tauri_android.py`，向生成工程注入移动端 HTML 预览使用的 `HtmlPreviewActivity`。`src-tauri/gen/` 仍是生成目录，不提交到仓库。

构建 Android：

```bash
npm run tauri:android -- --apk
```

当前仓库也保留了 debug APK 构建路径，便于在 CI 中稳定产出可安装 APK：

```bash
npm run tauri:android:debug -- --apk
```

## 5. 平台依赖说明

### Linux

构建 Tauri 桌面端通常需要：

```bash
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev \
  patchelf
```

### macOS

- 可构建 `.dmg`
- 如需签名 / notarization，需额外配置 Apple 证书与 secrets
- 当前 Release workflow 预留了后续接入空间

### Windows

- 可构建 `.exe` / `.msi`
- 若后续需要代码签名，可在 CI 中继续补证书配置

### Android

需要：

- Java 17
- Android SDK
- Android NDK
- Rust Android targets

Release workflow 会分别为 Console 和 Chat 构建 `arm64-v8a`、`armeabi-v7a`、`x86`、`x86_64` 的签名 release APK。发布环境必须配置 `ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS` 和 `ANDROID_KEY_PASSWORD`；缺少任一 secret 时 Android 发布任务会失败。

## 6. Git Hook 集成

仓库内已提供可版本化维护的 git hooks：

```text
.githooks/pre-commit
.githooks/pre-tag
```

安装方式：

```bash
bash scripts/install_git_hooks.sh
```

安装后：

- `pre-commit` 会继续执行 Python 的 `ruff + mypy`
- 当提交里包含 `apps/undefined-console/`、`apps/undefined-chat/`、`src/Undefined/webui/static/js/`、`biome.json`、CI workflow 相关改动时，还会额外执行对应 App 的：
  - `Biome` 检查
  - `TypeScript` 类型检查
  - `cargo fmt --check`
  - `cargo check`

说明：如果本机还没安装 App 依赖，需要先执行：

```bash
cd apps/undefined-console
npm install
cd ../undefined-chat
npm install
```

## 7. Release 工作流

当前 tag 发布工作流位于：

```text
.github/workflows/release.yml
```

触发条件：

- 推送 tag：`v*`

工作流主要阶段：

1. `verify-python`：校验 tag、构建版本和 `CHANGELOG.md` 最新版本一致，并执行 `ruff`、`mypy`、`pytest`、`uv build`。
2. `verify-native-app`：分别对 Console 和 Chat 执行 `npm run check`。
3. `build-tauri-desktop`：分别构建 Console / Chat 的 Linux `.AppImage` / `.deb`、Windows `.exe` / `.msi`、macOS x64 `.dmg` 和 macOS arm64 `.dmg`。
4. `build-tauri-android`：分别构建 Console / Chat 的 Android `.apk`。
5. `publish-release`：汇总所有产物并上传 GitHub Release；Release notes 从 `CHANGELOG.md` 最新版本条目生成，不读取 tag 注释。
6. `publish-pypi`：发布 Python 包到 PyPI。

## 8. 手动 Artifact 工作流

如果只想让 GitHub Actions 编译一次原生 App 并从 workflow run 页面手动下载产物，不创建 GitHub Release，也不发布 PyPI，可以使用：

```text
.github/workflows/manual-native-artifacts.yml
```

触发方式：

- `workflow_dispatch`

默认输入会构建 `Undefined Chat`：

- 桌面端：Linux `.AppImage` / `.deb`、Windows `.exe` / `.msi`、macOS x64 / arm64 `.dmg`
- Android：`arm64-v8a` debug APK

可选输入：

- `source_ref`：要构建的分支、tag 或 SHA；留空时使用 Actions 页面选择的 ref。
- `product`：`chat`、`console` 或 `all`。
- `build_desktop`：是否构建桌面端。
- `desktop_platform`：`all`、`linux`、`windows` 或 `macos`。
- `build_android_debug`：是否构建 Android debug APK。
- `android_abi`：`arm64-v8a`、`armeabi-v7a`、`x86`、`x86_64` 或 `all`。

手动 artifact 工作流的边界：

- 不调用 `gh release create`。
- 不发布 Python 包到 PyPI。
- Android 只构建 debug APK，不需要配置 release keystore secrets。
- artifacts 通过 `actions/upload-artifact` 上传到 workflow run，默认保留 14 天。

注意：GitHub 的 `workflow_dispatch` 手动入口通常要求 workflow 文件已存在于默认分支。若该文件只存在于 feature 分支，Actions 页面可能不会显示这个手动 workflow；将该 workflow 文件合入默认分支后，可在运行时通过 `source_ref` 指向任意待构建分支，例如 `feature/chat-app`。

## 9. Release 产物矩阵

每次正式 Release 计划上传：

- Python
  - `wheel`
  - `sdist`
- Windows
  - `Undefined-Console-*-windows-x64-setup.exe`
  - `Undefined-Console-*-windows-x64.msi`
  - `Undefined-Chat-*-windows-x64-setup.exe`
  - `Undefined-Chat-*-windows-x64.msi`
- Linux
  - `Undefined-Console-*-linux-x64.AppImage`
  - `Undefined-Console-*-linux-x64.deb`
  - `Undefined-Chat-*-linux-x64.AppImage`
  - `Undefined-Chat-*-linux-x64.deb`
- macOS
  - `Undefined-Console-*-macos-x64.dmg`
  - `Undefined-Console-*-macos-arm64.dmg`
  - `Undefined-Chat-*-macos-x64.dmg`
  - `Undefined-Chat-*-macos-arm64.dmg`
- Android
  - `Undefined-Console-*-android-*-release.apk`
  - `Undefined-Chat-*-android-*-release.apk`

`iOS` 当前不在发布矩阵内。

## 10. 推荐的本地构建顺序

如果你准备发布一个版本，建议本地先按以下顺序自检：

```bash
uv sync --group dev -p 3.12
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest tests/
uv build
```

如果本次改动涉及 App：

```bash
cd apps/undefined-console
npm install
npm run check  # 代码检查与测试（lint/typecheck/test/cargo fmt/check/test，具体以 package.json 为准）
# 注意：npm run tauri:build 会自动执行 npm run build，无需手动构建前端

cd ../undefined-chat
npm install
npm run check  # Biome、TypeScript、unit/jsdom integration tests、cargo fmt/check/test
```

如果本次改动涉及 Android 构建链：

```bash
npm run tauri:android:init
npm run tauri:android:prepare:check  # Undefined Chat 检查生成工程已包含 HtmlPreviewActivity
npm run tauri:android:debug -- --apk
```

## 11. 常见建议

- 日常开发和首次部署，优先验证 `uv run Undefined-webui` 全流程是否顺畅。
- 改动管理接口时，优先补 `tests/test_webui_management_api.py`。
- 改动发布矩阵时，务必同步更新 `README.md`、[Undefined Chat](undefined-chat.md) 与本文件。
- 改动 App 构建脚本时，注意同时检查 `apps/undefined-console/package.json`、`apps/undefined-chat/package.json` 与 `.github/workflows/release.yml`。
