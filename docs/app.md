# 跨平台 App 与远程管理

Undefined 当前的跨平台 App（`apps/undefined-console/`）定位为：

- 保存多个远程连接档案
- 对 Management API / Runtime API 做基础连通性探测
- 在桌面端 / Android 中直接打开 **真正的远程 WebUI**

也就是说，它不是再维护一套长期独立演进的“第二后台”，而是作为 **连接器 + 容器**，尽量保证你最终看到的仍然是原生 WebUI 的完整体验与完整功能。

## 1. 支持范围

首期目标平台：

- Windows
- macOS
- Linux
- Android

说明：

- `iOS` 当前**不在发布矩阵内**
- Release workflow 会在打 tag 时同步构建并上传非 iOS 平台安装包

## 2. 为什么不再维护一套独立后台

浏览器版 WebUI 已经是项目里最完整、最稳定、最好看的控制台。

如果 Tauri 内再维护一套平行后台，会带来两个问题：

1. UI 很容易和 WebUI 漂移
2. 功能很容易落后于 WebUI

所以当前策略是：

- **浏览器 WebUI 是唯一真源**
- **Tauri App 负责连接与打开这个真源**

## 3. 两种连接模式

### Management 模式（推荐）

适合日常运维与远程管理。

需要：

- `management_url`
- WebUI 密码（用于测试管理登录）

作用：

- 探测 Management API
- 直接打开真正的远程 WebUI

### Runtime-only 模式

适合只接运行态，只读或半只读使用。

需要：

- `runtime_url`
- `X-Undefined-API-Key`

作用：

- 探测 Runtime API 健康状态
- 查看运行态是否可达

不建议把 Runtime-only 模式当作主要远程运维方案，因为它无法替代完整 WebUI。

## 4. 推荐使用流程

1. 先在服务器或本机运行：

```bash
uv run Undefined-webui
```

2. 在浏览器中完成首次密码设置与配置补齐
3. 启动 Bot
4. 在桌面端或 Android App 中新增一个 `Management` 连接档案
5. 在 App 中点击“打开 WebUI”
6. 后续直接在 App 容器中使用真正的 WebUI

## 5. Android 适配说明

Android 端仍然走同一套连接模型，但 UI 目标是：

- 把 App 自身保持得尽量轻
- 让真正复杂的后台界面依旧由 WebUI 本体负责
- 尽量减少 Tauri 内再造一套移动版后台的维护成本

如果后续要补强 Android 体验，优先方向是：

- 优化连接页和启动页
- 优化打开远程 WebUI 前的引导
- 必要时对 WebUI 本体做移动端适配

## 6. Release 产物

每次 `v*` tag 发布时，Release workflow 计划同步上传：

- Python：`wheel` + `sdist`
- Windows：`.exe` + `.msi`
- Linux：`.AppImage` + `.deb`
- macOS：`.dmg`（Intel / Apple Silicon）
- Android：`.apk`

## 7. 本地开发

App 位于：

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

### 典型本地调试流程

1. 终端 1：

```bash
cd /data0/Undefined
uv run Undefined-webui
```

2. 终端 2：

```bash
cd /data0/Undefined/apps/undefined-console
npm run tauri:dev
```

3. 在 App 中：

- 填 `Management 地址`
- 填管理密码
- 点击“测试连接”
- 点击“打开 WebUI”

## 8. 结论

如果你要：

- **最完整功能**
- **最接近现有 WebUI 的视觉与交互**
- **尽量避免双份前端长期漂移**

那么当前最稳妥的路线就是：

- `Undefined-webui` 继续作为真正后台
- `Tauri App` 作为远程连接器和容器
