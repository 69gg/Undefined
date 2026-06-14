import { invoke } from "@tauri-apps/api/core";
import {
	type ReactNode,
	createContext,
	useContext,
	useEffect,
	useState,
} from "react";
import { DEFAULT_PLATFORM_INFO, type PlatformInfo } from "./types";

/**
 * 平台上下文 - 提供全局平台信息
 */
const PlatformContext = createContext<PlatformInfo>(DEFAULT_PLATFORM_INFO);

/**
 * 平台信息提供者组件
 */
export function PlatformProvider({ children }: { children: ReactNode }) {
	const [platform, setPlatform] = useState<PlatformInfo>(DEFAULT_PLATFORM_INFO);

	useEffect(() => {
		detectPlatform()
			.then(setPlatform)
			.catch((error) => {
				console.error("Failed to detect platform:", error);
			});
	}, []);

	return (
		<PlatformContext.Provider value={platform}>
			{children}
		</PlatformContext.Provider>
	);
}

/**
 * 使用平台信息的 Hook
 *
 * @returns 当前平台信息
 * @example
 * ```tsx
 * const platform = usePlatform();
 * if (platform.os === "android") {
 *   return <MobileView />;
 * }
 * ```
 */
export function usePlatform(): PlatformInfo {
	return useContext(PlatformContext);
}

/**
 * 检测平台信息
 *
 * 优先通过 Tauri 命令获取，失败时回退到浏览器信息
 */
async function detectPlatform(): Promise<PlatformInfo> {
	try {
		const info = await invoke<PlatformInfo>("get_platform_info");
		return info;
	} catch (error) {
		console.warn("Failed to invoke get_platform_info, using fallback:", error);
		return getFallbackPlatformInfo();
	}
}

/**
 * 回退平台检测（基于浏览器 API）
 */
function getFallbackPlatformInfo(): PlatformInfo {
	const ua = navigator.userAgent.toLowerCase();
	const isAndroid = ua.includes("android");
	const isIOS = /iphone|ipad|ipod/.test(ua);
	const isMac = ua.includes("mac");
	const isWindows = ua.includes("win");
	const isLinux = ua.includes("linux") && !isAndroid;

	let os = "unknown";
	let family = "unknown";

	if (isAndroid) {
		os = "android";
		family = "unix";
	} else if (isIOS) {
		os = "ios";
		family = "unix";
	} else if (isMac) {
		os = "macos";
		family = "unix";
	} else if (isWindows) {
		os = "windows";
		family = "windows";
	} else if (isLinux) {
		os = "linux";
		family = "unix";
	}

	return {
		os,
		family,
		arch: "unknown",
		debug: false,
		supportsSystemKeyring: false,
		supportsSecureApiKeyStorage: false,
		supportsSse: true,
		supportsHtmlPreview: false,
	};
}

/**
 * 判断是否为 Android 平台
 */
export function isAndroidPlatform(platform: PlatformInfo): boolean {
	return platform.os === "android";
}

/**
 * 判断是否为桌面平台
 */
export function isDesktopPlatform(platform: PlatformInfo): boolean {
	return ["windows", "macos", "linux"].includes(platform.os);
}

/**
 * 判断是否为移动平台
 */
export function isMobilePlatform(platform: PlatformInfo): boolean {
	return ["android", "ios"].includes(platform.os);
}
