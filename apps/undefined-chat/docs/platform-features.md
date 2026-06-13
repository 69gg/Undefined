# 桌面端平台功能

## 概述

本功能模块为 undefined-chat 桌面应用提供平台特定功能支持，包括快捷键管理、平台检测和桌面布局包装。

## 文件结构

```
src/platform/
├── KeybindingManager.ts          # 快捷键管理器
├── KeybindingManager.test.ts     # 快捷键管理器测试
├── DesktopLayout.tsx              # 桌面布局包装器
├── types.ts                       # 类型定义
├── index.ts                       # 模块导出
└── integration.test.tsx           # 集成测试
```

## 快捷键管理

### 默认快捷键

- **Ctrl+N**: 新建会话
- **Ctrl+/**: 切换侧边栏
- **Escape**: 关闭模态框
- **Ctrl+Enter**: 发送消息（由 MessageComposer 处理）

### 使用示例

```typescript
import { KeybindingManager } from "./platform";

const keybindingManager = useMemo(() => new KeybindingManager(), []);

useEffect(() => {
  // 注册快捷键
  keybindingManager.register("Ctrl+N", () => {
    void store.createConversation();
  });

  // 开始监听
  keybindingManager.startListening();

  // 清理
  return () => {
    keybindingManager.stopListening();
  };
}, [keybindingManager, store]);
```

### 特性

- **跨平台**: macOS 的 Cmd 键自动映射为 Ctrl
- **输入框智能过滤**: 在输入框中自动忽略快捷键（Escape 除外）
- **防止默认行为**: 自动阻止浏览器默认快捷键行为

## 平台检测

### Rust 后端

`src-tauri/src/platform.rs` 提供 `get_platform_info` 命令：

```rust
#[tauri::command]
pub fn get_platform_info() -> PlatformInfo {
    // 返回平台信息
}
```

### TypeScript 类型

```typescript
interface PlatformInfo {
  os: string;
  family: string;
  arch: string;
  debug: boolean;
  supportsSystemKeyring: boolean;
  supportsSse: boolean;
  supportsHtmlPreview: boolean;
}
```

### 在 App.tsx 中使用

```typescript
useEffect(() => {
  async function init() {
    try {
      const platformInfo = await invoke<RustPlatformInfo>("get_platform_info");
      console.log("平台信息:", platformInfo);
    } catch (err) {
      console.warn("无法获取平台信息:", err);
    }
    await store.bootstrap();
  }
  void init();
}, [store]);
```

## 桌面布局

`DesktopLayout` 组件为桌面端提供布局包装：

```typescript
<DesktopLayout enableCustomTitleBar={false}>
  <main className="chat-app">
    {/* 应用内容 */}
  </main>
</DesktopLayout>
```

### 未来扩展

- 自定义标题栏（data-tauri-drag-region）
- 原生菜单栏集成
- 平台特定样式调整

## 测试

运行平台相关测试：

```bash
npm test -- src/platform/KeybindingManager.test.ts
npm test -- src/platform/integration.test.tsx
```

测试覆盖：
- ✅ 快捷键注册与注销
- ✅ 键盘事件处理
- ✅ 组合键支持（Ctrl+Alt+Shift）
- ✅ 输入框过滤
- ✅ 布局组件渲染
- ✅ 平台类型定义

## 集成到现有代码

### App.tsx 主要修改

1. 导入 platform 模块
2. 添加 `showModal` 状态前置声明
3. 创建 `keybindingManager` 实例
4. 平台信息检测
5. 注册默认快捷键
6. 使用 `DesktopLayout` 包装应用

## 已知问题

- `test-fixtures.ts` 和 `HtmlPreview.test.tsx` 存在类型错误，这些是已存在的问题，与新增功能无关
- 平台信息当前仅用于日志输出，未来可用于条件渲染和功能开关

## 后续工作

- [ ] 实现命令面板（Ctrl+K）
- [ ] 添加更多快捷键（如：Ctrl+,打开设置）
- [ ] 平台信息存入 store
- [ ] 自定义标题栏支持
- [ ] 原生菜单栏集成
- [ ] 快捷键配置持久化
