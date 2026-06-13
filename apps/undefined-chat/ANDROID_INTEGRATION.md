# Android 功能集成指南

## 已完成的工作

本次实现为 undefined-chat 添加了 Android 特定功能支持：

### 1. 新增文件

#### `src/platform/ConnectionSetup.tsx`
Android 连接配置组件，提供：
- Runtime URL 和 API Key 配置表单
- 历史配置列表（最近使用的 5 个配置）
- 本地存储管理（localStorage）
- URL 格式验证
- 友好的移动端 UI

#### `src/platform/AndroidLifecycle.ts`
Android 生命周期管理模块，提供：
- `setupAndroidLifecycle(store)`: 监听应用暂停/恢复事件
- `isAndroid()`: 检测是否在 Android 平台运行
- 自动重连和事件补齐机制

#### `src/platform/ConnectionSetup.test.tsx`
ConnectionSetup 组件的单元测试

#### `src/platform/AndroidLifecycle.test.ts`
AndroidLifecycle 模块的单元测试

### 2. 更新的文件

#### `src/platform/index.ts`
新增导出：
```typescript
export { ConnectionSetup } from "./ConnectionSetup";
export type { ConnectionSetupProps, RuntimeConfig } from "./ConnectionSetup";
export { setupAndroidLifecycle, isAndroid } from "./AndroidLifecycle";
```

#### `src/styles.css`
在文件末尾添加了 `ConnectionSetup` 组件的完整样式，包括：
- 响应式居中布局
- 卡片样式容器
- 表单元素样式
- 历史配置列表样式
- 错误提示样式
- 连接按钮样式
- 提示信息样式

### 3. 需要手动集成到 `src/App.tsx` 的更改

#### 3.1 添加导入

在文件顶部添加：

```typescript
import { invoke } from "@tauri-apps/api/core";
// ... 现有导入
import { ImageViewerModal, useImageViewer } from "./image-viewer";
// ... 现有导入
import {
	ConnectionSetup,
	DesktopLayout,
	KeybindingManager,
	isAndroid,
	setupAndroidLifecycle,
} from "./platform";
import type { PlatformInfo as RustPlatformInfo } from "./platform/types";
```

#### 3.2 添加状态和 hooks

在 `App()` 函数内部，在现有 hooks 后添加：

```typescript
// 快捷键管理器
const keybindingManager = useMemo(() => new KeybindingManager(), []);

// 图片查看器
const { closeImage } = useImageViewer(store);

const showModal = needsSetup || isSettingsOpen;
```

#### 3.3 更新 bootstrap effect

将现有的：
```typescript
useEffect(() => {
	void store.bootstrap();
}, [store]);
```

替换为：
```typescript
// 启动时检测平台信息和初始化
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

// Android 生命周期管理
useEffect(() => {
	if (isAndroid()) {
		console.log("[App] Android platform detected, setting up lifecycle");
		const cleanup = setupAndroidLifecycle(store);
		return cleanup;
	}
	return undefined;
}, [store]);
```

#### 3.4 添加快捷键支持

在现有 effects 后添加：

```typescript
// 注册快捷键
useEffect(() => {
	// Ctrl+N：新建会话
	keybindingManager.register("Ctrl+N", () => {
		void store.createConversation();
	});

	// Ctrl+/：切换侧边栏
	keybindingManager.register("Ctrl+/", () => {
		setIsSidebarCollapsed((prev) => !prev);
	});

	// Escape：关闭模态框
	keybindingManager.register("Escape", () => {
		if (!needsSetup && isSettingsOpen) {
			setIsSettingsOpen(false);
		}
	});

	keybindingManager.startListening();

	return () => {
		keybindingManager.stopListening();
	};
}, [keybindingManager, store, needsSetup, isSettingsOpen]);
```

#### 3.5 添加 ConnectionSetup 处理函数

在现有的 `handleSetupSubmit` 函数后添加：

```typescript
async function handleConnectionSetup(url: string, apiKey: string) {
	setSetupError(null);
	try {
		await client.saveRuntimeConfig(url);
		await client.saveApiKey(apiKey);
		setSetupRuntimeUrl(url);
		await store.bootstrap();
	} catch (err) {
		setSetupError(err instanceof Error ? err.message : String(err));
	}
}
```

#### 3.6 添加 Android 专用启动界面

在 `return` 语句之前（函数末尾），添加：

```typescript
// Android 平台使用专用的连接设置界面
if (isAndroid() && needsSetup) {
	return (
		<DesktopLayout>
			<ConnectionSetup
				currentUrl={setupRuntimeUrl}
				onConnect={handleConnectionSetup}
			/>
		</DesktopLayout>
	);
}
```

#### 3.7 添加 ImageViewerModal

在现有的 `return` 语句的 `</DesktopLayout>` 结束标签前添加：

```typescript
		</main>
		<ImageViewerModal imageViewer={state.imageViewer} onClose={closeImage} />
	</DesktopLayout>
```

#### 3.8 修复一个现有 lint 问题

在 `src/image-viewer/ImageViewerModal.tsx` 中移除冗余的 `role="img"` 属性：

将：
```typescript
<img
	src={imageViewer.src}
	alt={imageViewer.alt}
	onClick={(e) => e.stopPropagation()}
	onKeyDown={(e) => e.stopPropagation()}
	role="img"  // 删除这一行
/>
```

改为：
```typescript
<img
	src={imageViewer.src}
	alt={imageViewer.alt}
	onClick={(e) => e.stopPropagation()}
	onKeyDown={(e) => e.stopPropagation()}
/>
```

## 功能说明

### ConnectionSetup 组件

当 Android 应用首次启动或配置丢失时，会显示专用的连接配置界面：

1. **Runtime URL 输入框**: 用户输入 Undefined Runtime 服务器地址（通常是局域网 IP）
2. **API Key 输入框**: 用户输入 API 密钥
3. **最近使用列表**: 自动记录最近使用的 5 个配置，点击可快速填充
4. **表单验证**: 
   - 必填字段验证
   - URL 格式验证
   - 错误提示显示
5. **本地存储**: 配置历史保存在 `localStorage` 的 `undefined-runtime-history` 键中

### Android 生命周期管理

`setupAndroidLifecycle(store)` 监听两个关键事件：

1. **android-pause**: 应用进入后台时触发
   - 记录日志
   - 可选：保存状态或清理资源

2. **android-resume**: 应用恢复到前台时触发
   - 重新调用 `store.bootstrap()` 建立连接
   - 自动检测活跃任务
   - 自动恢复事件流订阅
   - 补齐暂停期间遗漏的事件

### 平台检测

`isAndroid()` 函数通过检测 `navigator.userAgent` 中是否包含 "Android" 来判断平台。

## 测试

运行测试：

```bash
npm test src/platform/ConnectionSetup.test.tsx
npm test src/platform/AndroidLifecycle.test.ts
```

## 样式定制

所有样式都在 `src/styles.css` 的 `Connection Setup (Android)` 区块中，支持：
- 浅色/深色主题自动适配
- 响应式布局
- 流畅的动画效果
- Morandi 橙色主题配色

## 后续工作

1. 在 Rust 后端实现 `android-pause` 和 `android-resume` 事件的发送
2. 测试实际 Android 设备上的生命周期行为
3. 优化事件补齐逻辑的性能
4. 添加离线状态指示器

## 注意事项

- ConnectionSetup 只在 `isAndroid() && needsSetup` 时显示
- 桌面端继续使用原有的模态框配置方式
- 历史配置存储在浏览器 localStorage，不会跨设备同步
- 生命周期管理仅在 Android 平台激活
