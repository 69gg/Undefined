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
	PlatformProvider,
	usePlatform,
	isAndroidPlatform,
	isDesktopPlatform,
	isMobilePlatform,
} from "./PlatformContext";
export { KeybindingManager } from "./KeybindingManager";
export type { KeybindingHandler } from "./KeybindingManager";
export { DesktopLayout } from "./DesktopLayout";
export type { DesktopLayoutProps } from "./DesktopLayout";
export { ConnectionSetup } from "./ConnectionSetup";
export type { ConnectionSetupProps, RuntimeConfig } from "./ConnectionSetup";
export {
	setupAndroidLifecycle,
	isAndroid,
} from "./AndroidLifecycle";
export type { PlatformInfo } from "./types";
export { DEFAULT_PLATFORM_INFO } from "./types";
