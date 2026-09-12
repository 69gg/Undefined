/**
 * Platform 模块 - 跨平台特定功能
 *
 * 导出：
 * - PlatformProvider/usePlatform: 平台信息上下文
 * - KeybindingManager: 快捷键管理
 * - DesktopLayout: 桌面端布局包装器
 * - ConnectionSetup: Android 连接配置组件
 * - AndroidLifecycle: Android 生命周期管理
 * - PlatformInfo: 平台信息类型
 */

export {
	isAndroid,
	setupAndroidLifecycle,
} from "./AndroidLifecycle";
export type { ConnectionSetupProps, RuntimeConfig } from "./ConnectionSetup";
export { ConnectionSetup } from "./ConnectionSetup";
export type { DesktopLayoutProps } from "./DesktopLayout";
export { DesktopLayout } from "./DesktopLayout";
export type { KeybindingHandler } from "./KeybindingManager";
export { KeybindingManager } from "./KeybindingManager";
export {
	isAndroidPlatform,
	isDesktopPlatform,
	isMobilePlatform,
	PlatformProvider,
	usePlatform,
} from "./PlatformContext";
export type { PlatformInfo } from "./types";
export { DEFAULT_PLATFORM_INFO } from "./types";
