# 构建指南

本文档说明 Undefined 当前仓库中的主要构建方式，包括：

- Python 包构建（`wheel` / `sdist`）
- `Undefined-webui` 管理控制台的本地开发与验证
- 跨平台连接器 `apps/undefined-console/` 的桌面端 / Android 构建
- GitHub Release 工作流的发布矩阵

> 约定：
>
> - 浏览器版管理入口仍然是 `uv run Undefined-webui`
> - 桌面端 / Android App 是额外的连接器 / 容器，不替代 `Undefined-webui`
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

### Node.js / Rust / Tauri

如果需要构建跨平台控制台，请额外准备：

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

## 4. 跨平台控制台 App

当前 App 的职责不是维护一套长期独立的第二后台，而是：

- 保存连接档案
- 测试 Management / Runtime 入口
- 直接打开真正的远程 WebUI

跨平台客户端位于：

```text
apps/undefined-console/
```

### 安装依赖

```bash
cd apps/undefined-console
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

### Android 初始化与构建

首次或 CI 环境中，先初始化 Android 项目：

```bash
npm run tauri:android:init
```

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

CI 当前会优先保证每个 release 至少产出一个可安装 APK；如果后续接入正式签名，可再升级为签名 release APK / AAB。

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
- 当提交里包含 `apps/undefined-console/`、`src/Undefined/webui/static/js/`、`biome.json`、CI workflow 相关改动时，还会额外执行：
  - `Biome` 检查
  - `TypeScript` 类型检查
  - `cargo fmt --check`
  - `cargo check`

说明：如果本机还没安装 App 依赖，需要先执行：

```bash
cd apps/undefined-console
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

1. `verify-python`
   - `ruff`
   - `mypy`
   - `pytest`
   - `uv build`
2. `build-tauri-desktop`
   - Linux：`.AppImage` + `.deb`
   - Windows：`.exe` + `.msi`
   - macOS x64：`.dmg`
   - macOS arm64：`.dmg`
3. `build-tauri-android`
   - Android 通用 `.apk`
4. `publish-release`
   - 汇总所有产物并上传 GitHub Release
5. `publish-pypi`
   - 发布 Python 包到 PyPI

## 8. Release 产物矩阵

每次正式 Release 计划上传：

- Python
  - `wheel`
  - `sdist`
- Windows
  - `.exe`
  - `.msi`
- Linux
  - `.AppImage`
  - `.deb`
- macOS
  - Intel `.dmg`
  - Apple Silicon `.dmg`
- Android
  - `.apk`

`iOS` 当前不在发布矩阵内。

## 9. 推荐的本地构建顺序

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
npm run check  # 代码检查（lint + typecheck + cargo check）
# 注意：npm run tauri:build 会自动执行 npm run build，无需手动构建前端
```

如果本次改动涉及 Android 构建链：

```bash
npm run tauri:android:init
npm run tauri:android:debug -- --apk
```

## 10. 常见建议

- 日常开发和首次部署，优先验证 `uv run Undefined-webui` 全流程是否顺畅。
- 改动管理接口时，优先补 `tests/test_webui_management_api.py`。
- 改动发布矩阵时，务必同步更新 `README.md` 与本文件。
- 改动 App 构建脚本时，注意同时检查 `apps/undefined-console/package.json` 与 `.github/workflows/release.yml`。
