# 跨平台 App 与远程管理

Undefined 现在提供一套新的跨平台控制台骨架，用于连接 `Undefined-webui` 暴露的 Management API。

## 1. 支持范围

首期目标平台：

- Windows
- macOS
- Linux
- Android

说明：

- `iOS` 当前**不在发布矩阵内**
- Release workflow 会在打 tag 时同步构建并上传非 iOS 平台安装包

## 2. 两种连接模式

### Management 模式（推荐）

适合日常运维与远程管理。

需要：

- `management_url`
- WebUI 密码（首次）

能力范围：

- 登录 / token 刷新
- bootstrap probe
- 配置读写 / 校验 / 模板同步
- 日志读取 / 流式 tail
- 系统信息
- Bot 启停
- Runtime API 代理访问

### Runtime-only 模式

适合只接运行态，只读或半只读使用。

需要：

- `runtime_url`
- `X-Undefined-API-Key`

能力范围通常限制在：

- internal/external probes
- memory
- cognitive
- chat/history
- runtime openapi

不建议把 Runtime-only 模式当作主要远程运维方案，因为它不能替代配置救援和日志控制面。

## 3. 推荐使用流程

1. 先在服务器或本机运行：

```bash
uv run Undefined-webui
```

2. 在浏览器中完成首次密码设置与配置补齐
3. 启动 Bot
4. 在桌面端或 Android App 中新增一个 `Management` 连接档案
5. 后续直接用 App 远程管理该实例

## 4. Android 适配说明

移动端不会简单复用桌面布局，而是优先走适合触控的小屏交互：

- 底部或窄屏导航
- 单列布局
- 分段式配置编辑
- 更适合触屏的探针与日志查看
- 安全区 / 软键盘 / 弱网处理

当前仓库中的 `apps/undefined-console/` 提供了桌面端与 Android 共用的前端壳与 `Tauri v2` 项目骨架。

## 5. Release 产物

每次 `v*` tag 发布时，Release workflow 计划同步上传：

- Python：`wheel` + `sdist`
- Windows：`.exe` + `.msi`
- Linux：`.AppImage` + `.deb`
- macOS：`.dmg`（Intel / Apple Silicon）
- Android：`.apk`

## 6. 本地开发

App 骨架位于：

- `apps/undefined-console/`

常用命令：

```bash
cd apps/undefined-console
npm install
npm run dev
npm run tauri:dev
npm run tauri:build
npm run tauri:android:init
npm run tauri:android -- --apk
```

如果你只想继续使用浏览器版控制台，也完全没问题；`uv run Undefined-webui` 依然是默认、最推荐的入口。
