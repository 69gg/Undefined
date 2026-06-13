/**
 * 平台信息类型定义（与 Rust 后端 PlatformInfo 对应）
 */
export interface PlatformInfo {
	os: string;
	family: string;
	arch: string;
	debug: boolean;
	supportsSystemKeyring: boolean;
	supportsSse: boolean;
	supportsHtmlPreview: boolean;
}

/**
 * 默认平台信息（用于初始状态或 Web 环境）
 */
export const DEFAULT_PLATFORM_INFO: PlatformInfo = {
	os: "unknown",
	family: "unknown",
	arch: "unknown",
	debug: false,
	supportsSystemKeyring: false,
	supportsSse: true,
	supportsHtmlPreview: false,
};
