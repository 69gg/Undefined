# 跨平台 App 与远程管理

Undefined 当前的跨平台 App（`apps/undefined-console/`）定位为：

- 保存多个远程连接档案
- 对 Management API / Runtime API 做基础连通性探测
- 在桌面端 / Android 中直接打开 **真正的远程 WebUI**

也就是说，它不是再维护一套长期独立演进的“第二后台”，而是作为 **连接器 / 启动器**，尽量保证你最终看到的仍然是原生 WebUI 的完整体验与完整功能。

## 1. 支持范围

首期目标平台：

- Windows
- macOS
- Linux
- Android

说明：

- `iOS` 当前**不在发布矩阵内**
- Release workflow 会在打 tag 时同步构建并上传非 iOS 平台安装包

## 2. App 的职责

Tauri App 当前不再尝试长期维护一套平行后台。它的职责是：

1. 保存远程实例连接配置
2. 做基础连通性探测
3. 自动尝试登录 Management API
4. 把语言 / 主题偏好透传给远程 WebUI
5. 直接打开真正的 WebUI

换句话说：

- **浏览器 WebUI 是唯一真源**
- **Tauri App 负责连接与打开这个真源**

## 3. 连接模型

每个连接现在使用以下字段：

- `显示名称`
- `IP / 域名`
- `Management 端口`
- `Runtime 端口`
- `管理密码`
- `备注`

这样做的好处是：

- 不再要求用户手写两个完整 URL
- 更适合桌面端和移动端录入
- 同一个主机下的两个服务端口更容易一起管理

## 4. Management 与 Runtime 的作用

### Management

作用：

- 测试 Management API 是否可达
- 自动登录（如果填写了管理密码）
- 打开真正的 WebUI

### Runtime

作用：

- 做 Runtime API 健康检查
- 确认 OpenAPI 与运行态是否可达

说明：Runtime 只是辅助探测，不负责替代完整后台。

## 5. 语言 / 主题 / 自动登录

当你在 App 中点击“打开 WebUI”时，当前实现会：

1. 如果填写了管理密码，先尝试调用登录接口
2. 再把当前的 `lang/theme` 偏好透传给远程 WebUI
3. 默认直接跳到 WebUI 的 `app` 视图（不是 landing）

这意味着：

- App 里切到英文 / 暗色后，打开 WebUI 会尽量保持一致
- 如果自动登录成功，进入 WebUI 后会直接是已登录状态
- 如果自动登录失败，则会落到 WebUI 登录页
- 从 WebUI 退出登录后，会回到主界面而不是停留在管理页

## 6. 推荐使用流程

1. 先在服务器或本机运行：

```bash
uv run Undefined-webui
```

2. 在浏览器中完成首次密码设置与配置补齐
3. 启动 Bot
4. 在桌面端或 Android App 中新增一个连接档案
5. 点击“测试连接”确认 Management / Runtime 可达
6. 点击“打开 WebUI”后，如已填写管理密码会先自动登录，再进入真正后台

## 7. Android 适配说明

Android 端仍然走同一套连接模型，但 UI 目标是：

- 把 App 自身保持得尽量轻
- 让真正复杂的后台界面依旧由 WebUI 本体负责
- 尽量减少 Tauri 内再造一套移动版后台的维护成本

如果后续要补强 Android 体验，优先方向是：

- 优化连接页和启动页
- 优化打开远程 WebUI 前的引导
- 必要时对 WebUI 本体做移动端适配

## 8. Release 产物

每次 `v*` tag 发布时，Release workflow 计划同步上传：

- Python：`wheel` + `sdist`
- Windows：`.exe` + `.msi`
- Linux：`.AppImage` + `.deb`
- macOS：`.dmg`（Intel / Apple Silicon）
- Android：`.apk`

## 9. 本地开发

App 位于：

- `apps/undefined-console/`

常用命令：

```bash
cd apps/undefined-console
npm install
npm run dev
npm run tauri:dev
npm run tauri:build
npm run tauri:build:no-strip
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

- 填 `IP / 域名`
- 填 `Management 端口`
- 需要时填 `Runtime 端口`
- 填管理密码
- 点击“测试连接”
- 点击“打开 WebUI”

## 10. 结论

如果你要：

- **最完整功能**
- **最接近现有 WebUI 的视觉与交互**
- **尽量避免双份前端长期漂移**

那么当前最稳妥的路线就是：

- `Undefined-webui` 继续作为真正后台
- `Tauri App` 作为远程连接器和启动器
