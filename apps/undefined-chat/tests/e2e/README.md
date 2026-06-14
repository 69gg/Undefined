# jsdom 集成测试

`tests/e2e/` 目录使用 Vitest + Testing Library + jsdom 运行 App 级流程测试。它们验证 React 状态、Runtime client mock、Tauri API mock 和用户交互，不是真实 Tauri WebView、浏览器或 Android 端到端测试。

## 测试文件

```text
tests/e2e/
├── connection-setup.test.tsx        # Runtime 配置与 API Key 表单
├── conversation-management.test.tsx # 会话创建、切换、删除
├── message-sending.test.tsx         # 消息发送、草稿、运行中限制
├── attachment-upload.test.tsx       # 附件队列、上传状态、错误处理
├── command-execution.test.tsx       # 斜杠命令和键盘补全
└── history-loading.test.tsx         # 历史加载和分页
```

## 运行

```bash
npm run test:e2e
npm run test:e2e -- history-loading.test.tsx
npm run test:unit
npm run test:all
npm run check
```

`npm run check` 还会运行 Biome、TypeScript、cargo fmt/check/test。

## 覆盖范围

已覆盖：

- 初始连接配置、保存配置、显式不安全存储降级。
- 会话创建、切换、删除确认和移动端侧栏基本行为。
- 消息发送、运行中禁发、空消息拦截、草稿隔离。
- 附件选择、上传中/成功/失败状态、发送时附件 ID。
- 命令面板打开、过滤、方向键、Tab/Enter 补全、Escape 关闭。
- 历史初始加载、时间顺序、加载更早消息、缓存、错误态。

## 不覆盖的真实平台风险

jsdom 不能覆盖：

- Tauri WebView 真实窗口行为和 HTML preview window close/destroy 清理。
- Android `content://` provider 实读、权限生命周期和大文件上传。
- 软键盘、安全区、刘海屏和真实触控目标。
- 后台/前台生命周期恢复和系统暂停 SSE 的行为。
- 原生 keyring/Stronghold 在不同桌面发行版或移动端的可用性。
- 浏览器/设备截图回归、Tab 焦点顺序和性能预算。

这些需要 Playwright/真机 smoke 或发布前手动 checklist 补充。

## 编写建议

- 优先使用 `getByRole`、`getByLabelText` 等语义查询。
- 使用 `runtimeClientStub` mock Runtime 行为，避免测试依赖网络。
- 使用 `await screen.findBy...` 或 `waitFor` 等待异步状态。
- 测试文件中 `beforeEach` 调用 `vi.resetAllMocks()`。
- 对滚动、blob URL、matchMedia、Tauri dialog 等 jsdom 缺失能力，优先在 `src/test-setup.ts` 提供集中 mock。
