# PlatformContext 使用指南

## 概述

`PlatformContext` 提供了跨平台的平台信息检测和上下文管理，支持桌面端（Windows/macOS/Linux）和移动端（Android）。

## 基础用法

### 1. 在应用根组件包装 PlatformProvider

```tsx
import { PlatformProvider } from "./platform/PlatformContext";

function App() {
  return (
    <PlatformProvider>
      <YourApp />
    </PlatformProvider>
  );
}
```

### 2. 在任意子组件中使用 usePlatform Hook

```tsx
import { usePlatform } from "./platform/PlatformContext";

function MyComponent() {
  const platform = usePlatform();
  
  return (
    <div>
      <p>当前系统: {platform.os}</p>
      <p>架构: {platform.arch}</p>
    </div>
  );
}
```

## 平台信息字段

```typescript
interface PlatformInfo {
  os: string;                          // 操作系统: "windows" | "macos" | "linux" | "android" | "ios" | "unknown"
  family: string;                      // 系统家族: "windows" | "unix" | "unknown"
  arch: string;                        // 架构: "x86_64" | "aarch64" | "unknown"
  debug: boolean;                      // 是否为调试构建
  supportsSystemKeyring: boolean;      // 是否支持系统密钥链
  supportsSecureApiKeyStorage: boolean; // 是否支持安全的 API Key 存储
  supportsSse: boolean;                // 是否支持 SSE 流式传输
  supportsHtmlPreview: boolean;        // 是否支持 HTML 预览
}
```

> 类型定义与默认值见 `src/platform/types.ts`（`PlatformInfo` / `DEFAULT_PLATFORM_INFO`），与 Rust 后端 `PlatformInfo` 对应。

## 条件渲染示例

### 根据平台类型渲染不同 UI

```tsx
import { usePlatform, isAndroidPlatform, isDesktopPlatform } from "./platform/PlatformContext";

function AdaptiveUI() {
  const platform = usePlatform();
  
  if (isAndroidPlatform(platform)) {
    return <MobileView />;
  }
  
  if (isDesktopPlatform(platform)) {
    return <DesktopView />;
  }
  
  return <DefaultView />;
}
```

### 根据操作系统显示快捷键

```tsx
function ShortcutHint() {
  const platform = usePlatform();
  const modifier = platform.os === "macos" ? "Cmd" : "Ctrl";
  
  return (
    <div>
      按 <kbd>{modifier}+K</kbd> 打开命令面板
    </div>
  );
}
```

### 根据平台能力启用功能

```tsx
function FeatureComponent() {
  const platform = usePlatform();
  
  return (
    <div>
      {platform.supportsSystemKeyring && (
        <button onClick={saveToKeychain}>保存到系统密钥链</button>
      )}
      
      {platform.supportsHtmlPreview && (
        <button onClick={previewHtml}>预览 HTML</button>
      )}
      
      {platform.supportsSse ? (
        <StreamingChat />
      ) : (
        <PollingChat />
      )}
    </div>
  );
}
```

### Android 特定布局

```tsx
function ChatLayout() {
  const platform = usePlatform();
  
  return (
    <div className={isAndroidPlatform(platform) ? "mobile-layout" : "desktop-layout"}>
      {isAndroidPlatform(platform) ? (
        <>
          {/* Android: 底部导航 */}
          <BottomNavigation />
          <Content />
        </>
      ) : (
        <>
          {/* 桌面: 侧边栏 */}
          <Sidebar />
          <Content />
        </>
      )}
    </div>
  );
}
```

> 上例为模式示意。实际 `App.tsx` 的移动端判定取「真实移动平台 ∨ 窄视口断点」（`isNarrowViewport || isMobilePlatform(platform)`），以避免平板/移动设备横屏（>768px）被误判为桌面，详见上文「在 App.tsx 中的实际应用」。

## 工具函数

### isAndroidPlatform

判断是否为 Android 平台：

```tsx
import { isAndroidPlatform, usePlatform } from "./platform/PlatformContext";

const platform = usePlatform();
if (isAndroidPlatform(platform)) {
  // Android 特定逻辑
}
```

### isDesktopPlatform

判断是否为桌面平台（Windows/macOS/Linux）：

```tsx
import { isDesktopPlatform, usePlatform } from "./platform/PlatformContext";

const platform = usePlatform();
if (isDesktopPlatform(platform)) {
  // 桌面端特定逻辑
}
```

### isMobilePlatform

判断是否为移动平台（Android/iOS）：

```tsx
import { isMobilePlatform, usePlatform } from "./platform/PlatformContext";

const platform = usePlatform();
if (isMobilePlatform(platform)) {
  // 移动端特定逻辑
}
```

## 平台检测机制

1. **优先级**：优先通过 Tauri `get_platform_info` 命令获取准确的平台信息
2. **回退**：如果 Tauri 不可用（如 Web 环境），回退到基于 `navigator.userAgent` 的检测
3. **默认值**：初始状态使用 `DEFAULT_PLATFORM_INFO`，异步检测完成后更新

## 在 App.tsx 中的实际应用

`src/App.tsx` 已实际接入平台抽象层：`usePlatform()` 驱动真实平台判定，移动端布局取「真实移动平台 ∨ 窄视口断点」，桌面端用 `DesktopLayout` 包装工作区，Android 生命周期按真实平台启用。

```tsx
import { useMediaQuery } from "./hooks/useMediaQuery";
import { DesktopLayout } from "./platform/DesktopLayout";
import {
  isAndroidPlatform,
  isDesktopPlatform,
  isMobilePlatform,
  usePlatform,
} from "./platform/PlatformContext";

function App() {
  const platform = usePlatform();

  // 窄视口或真实移动平台均视为移动端：
  // 解决平板/移动设备横屏（>768px）被误判为桌面
  const isNarrowViewport = useMediaQuery("(max-width: 768px)");
  const isMobile = isNarrowViewport || isMobilePlatform(platform);

  // 以真实平台为准启用 Android 生命周期（替代旧的 UA 判定）
  useEffect(() => {
    if (!isAndroidPlatform(platform)) {
      return undefined;
    }
    return setupAndroidLifecycle(store);
  }, [store, platform]);

  return (
    <main className="chat-app">
      <ConversationList isMobileActive={/* ... */} /* ... */ />

      <section className="chat-workspace">
        {/* 桌面平台用 DesktopLayout 透明包裹，预留平台增强位 */}
        <WorkspaceLayout isDesktop={isDesktopPlatform(platform)}>
          <header className="chat-topbar">{/* ... */}</header>
          <MessageTimeline />
          <MessageComposer />
        </WorkspaceLayout>
      </section>
    </main>
  );
}

/**
 * 桌面平台用 DesktopLayout（display:contents 透明包装，预留自定义标题栏/原生菜单），
 * 其它平台直接渲染子节点。
 */
function WorkspaceLayout({ isDesktop, children }: {
  isDesktop: boolean;
  children: ReactNode;
}) {
  return isDesktop ? <DesktopLayout>{children}</DesktopLayout> : <>{children}</>;
}
```

### DesktopLayout

桌面平台下包裹工作区的语义组件（`src/platform/DesktopLayout.tsx`）。当前以 `display: contents` 作透明包装——自身盒子从布局中消失，子元素直接参与 `.chat-workspace` 的 flex 列布局，不破坏现有布局，同时为自定义标题栏（`data-tauri-drag-region`）、原生菜单栏等桌面增强预留挂载点（`enableCustomTitleBar` 开关）。

### ConnectionSetup

统一的连接 / 配置组件（`src/platform/ConnectionSetup.tsx`），替代了早期内联的 setup 面板。支持两种模式：

- `mode="setup"`：首次连接，需填写 Runtime URL + API Key，无关闭按钮；
- `mode="settings"`：运行期修改配置，API Key 留空表示沿用原值，可关闭，并可通过 `children` 附加额外设置项（如自动滚动开关）。

内置最近使用的 Runtime 历史（localStorage，最多 5 条）、URL 必填与格式校验、全文案 i18n；持久化逻辑（保存配置→保存密钥→bootstrap）由调用方在 `onConnect` 中完成。`App.tsx` 据 `needsSetup` 在 `setup` / `settings` 间切换。

## 测试

```tsx
import { render, screen } from "@testing-library/react";
import { PlatformProvider, usePlatform } from "./platform/PlatformContext";

it("组件根据平台信息渲染", () => {
  function TestComponent() {
    const platform = usePlatform();
    return <div data-testid="os">{platform.os}</div>;
  }
  
  render(
    <PlatformProvider>
      <TestComponent />
    </PlatformProvider>
  );
  
  // 默认值
  expect(screen.getByTestId("os")).toHaveTextContent("unknown");
});
```

## 注意事项

1. **必须包装 PlatformProvider**：使用 `usePlatform` 的组件必须在 `PlatformProvider` 内部
2. **异步检测**：平台信息是异步获取的，初始渲染时使用默认值
3. **响应式设计**：`App.tsx` 已结合视口媒体查询（`useMediaQuery`）与平台检测（`isMobilePlatform`）判定移动端，两者取并集
4. **性能考虑**：平台信息在应用启动时检测一次，后续读取无性能开销
