/**
 * React hook for theme management
 * 使用 useSyncExternalStore 订阅主题变化，与现有 chat-store 保持一致
 */

import { useSyncExternalStore } from "react";
import { type EffectiveTheme, type Theme, themeManager } from "./theme-manager";

interface UseThemeReturn {
	/** 用户设置的主题偏好（light | dark | system） */
	theme: Theme;
	/** 当前有效主题（light | dark） */
	effectiveTheme: EffectiveTheme;
	/** 设置主题偏好 */
	setTheme: (theme: Theme) => void;
	/** 切换主题（light <-> dark） */
	toggleTheme: () => void;
}

export function useTheme(): UseThemeReturn {
	const theme = useSyncExternalStore(
		(callback) => themeManager.subscribe(callback),
		() => themeManager.getTheme(),
		() => themeManager.getTheme(),
	);

	const effectiveTheme = useSyncExternalStore(
		(callback) => themeManager.subscribe(callback),
		() => themeManager.getEffectiveTheme(),
		() => themeManager.getEffectiveTheme(),
	);

	return {
		theme,
		effectiveTheme,
		setTheme: (newTheme: Theme) => themeManager.setTheme(newTheme),
		toggleTheme: () => themeManager.toggleTheme(),
	};
}
