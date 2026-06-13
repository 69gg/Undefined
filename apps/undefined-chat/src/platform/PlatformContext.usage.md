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
  os: string;                      // 操作系统: "windows" | "macos" | "linux" | "android" | "ios" | "unknown"
  family: string;                  // 系统家族: "windows" | "unix" | "unknown"
  arch: string;                    // 架构: "x86_64" | "aarch64" | "unknown"
  debug: boolean;                  // 是否为调试构建
  supportsSystemKeyring: boolean;  // 是否支持系统密钥链
  supportsSse: boolean;            // 是否支持 SSE 流式传输
  supportsHtmlPreview: boolean;    // 是否支持 HTML 预览
}
```

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

```tsx
import { usePlatform, isDesktopPlatform } from "./platform/PlatformContext";

function App() {
  const platform = usePlatform();
  
  // 桌面端显示窗口控制按钮
  const showWindowControls = isDesktopPlatform(platform);
  
  // 移动端调整布局
  const isMobile = window.innerWidth <= 768 || platform.os === "android";
  
  return (
    <main className="chat-app">
      {showWindowControls && <WindowControls />}
      
      <Sidebar collapsed={isMobile} />
      
      <ChatWorkspace>
        {/* Android 显示简化版工具栏 */}
        {platform.os === "android" ? (
          <MobileToolbar />
        ) : (
          <DesktopToolbar />
        )}
        
        <MessageTimeline />
        <MessageComposer />
      </ChatWorkspace>
    </main>
  );
}
```

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
3. **响应式设计**：结合 CSS 媒体查询和平台检测实现最佳跨平台体验
4. **性能考虑**：平台信息在应用启动时检测一次，后续读取无性能开销
