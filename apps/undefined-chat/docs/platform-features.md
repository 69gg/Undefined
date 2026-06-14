# 平台能力说明

本文档记录 `apps/undefined-chat/src/platform/` 当前已接入的能力和限制。

## 快捷键

`KeybindingManager` 已在 `App.tsx` 接入。它把 macOS `Cmd` 映射为 `Ctrl`，并只在命中已注册快捷键时阻止默认行为。

当前默认绑定：

- `Ctrl/Cmd+N`：新建会话。
- `Ctrl/Cmd+K`：聚焦输入框；若草稿不是命令，则填入 `/` 并打开命令模式。
- `Ctrl/Cmd+/`：桌面切换侧栏折叠；移动端切换会话抽屉。
- `Ctrl/Cmd+,`：打开 Runtime 设置。
- `Escape`：关闭删除确认、设置面板或移动端抽屉。

`Enter` 发送、`Shift+Enter` 换行和命令面板内的方向键/Tab/Enter 由 `MessageComposer` 自己处理。

## 移动端布局

移动端使用 `useMediaQuery("(max-width: 768px)")` 切换布局：

- 会话列表作为抽屉打开，菜单按钮带 `aria-expanded` / `aria-controls`。
- 打开抽屉后焦点移入抽屉，关闭后尽量恢复到原触发元素。
- 输入区使用 `env(safe-area-inset-bottom)` 和 `window.visualViewport` 计算出的 `--keyboard-inset` 避让软键盘。
- 主要移动端点击控件在 CSS 中提升到 44px 最小触控目标。

jsdom 测试覆盖抽屉打开/关闭、ARIA 状态和 Escape 行为；软键盘、安全区和 Tab 顺序仍需要真实浏览器或设备验证。

## Android 生命周期

`setupAndroidLifecycle` 仅在 Android UA 下由 `App.tsx` 注册，监听 Tauri v2 官方事件：

- `tauri://suspended`
- `tauri://resumed`

恢复前台时会执行 `store.bootstrap()`，刷新 Runtime 配置、会话、当前历史页、active jobs，并重新建立事件订阅。SSE 断开或关闭后的事件补齐仍由 store 内部 JSON fallback 处理；当前没有单独暴露“resume 后逐 job 主动补齐”的公开接口。

## 文件与附件

附件上传通过 Tauri dialog 获取路径，然后调用 Rust command 流式上传：

- 桌面路径和 `file://` URL 会做本地 regular file 校验。
- Android `content://` URI 交给 `tauri-plugin-fs` 打开，不强制做本地 `metadata().is_file()` 校验，避免 content provider 兼容性问题。
- 前端只持有上传状态队列，不直接读取本地文件内容。

真实 Android content provider 读取仍必须通过设备 smoke 覆盖。

## 安全存储

`supports_system_keyring_target` 当前只支持 `linux`、`macos`、`windows`。Android/iOS 会返回不支持系统 keyring；保存 API Key 时只能在用户显式确认后写入不安全本地文件降级。

文档和 UI 不应宣称移动端安全存储已完整闭环，除非后续接入平台安全存储实现并补设备验证。

## 测试

常用命令：

```bash
npm run test:unit -- src/platform/KeybindingManager.test.ts src/platform/AndroidLifecycle.test.ts src/App.test.tsx
npm run check
```

`npm run check` 还会运行 TypeScript、Biome、jsdom integration tests、cargo fmt/check/test。真实 Tauri WebView、Android content URI、软键盘和后台恢复不在 jsdom 覆盖范围内。
