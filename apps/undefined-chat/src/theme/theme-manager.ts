/**
 * 主题管理器
 * 负责主题偏好的持久化、读取和系统偏好监听
 */

export type Theme = "light" | "dark" | "system";
export type EffectiveTheme = "light" | "dark";

const STORAGE_KEY = "undefined-chat-theme";
const DEFAULT_THEME: Theme = "system";

class ThemeManager {
	private theme: Theme = DEFAULT_THEME;
	private effectiveTheme: EffectiveTheme = "light";
	private listeners: Set<() => void> = new Set();
	private mediaQuery: MediaQueryList | null = null;

	constructor() {
		this.initialize();
	}

	private initialize(): void {
		// 读取持久化的主题偏好
		const stored = localStorage.getItem(STORAGE_KEY) as Theme | null;
		if (stored === "light" || stored === "dark" || stored === "system") {
			this.theme = stored;
		}

		// 监听系统主题偏好变化
		if (typeof window !== "undefined" && window.matchMedia) {
			this.mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
			this.mediaQuery.addEventListener("change", this.handleSystemThemeChange);
		}

		// 计算当前有效主题
		this.effectiveTheme = this.computeEffectiveTheme();
	}

	private handleSystemThemeChange = (): void => {
		if (this.theme === "system") {
			const newEffectiveTheme = this.computeEffectiveTheme();
			if (newEffectiveTheme !== this.effectiveTheme) {
				this.effectiveTheme = newEffectiveTheme;
				this.notifyListeners();
			}
		}
	};

	private computeEffectiveTheme(): EffectiveTheme {
		if (this.theme === "light") return "light";
		if (this.theme === "dark") return "dark";

		// system 模式：跟随系统偏好
		if (this.mediaQuery?.matches) {
			return "dark";
		}
		return "light";
	}

	private notifyListeners(): void {
		for (const listener of this.listeners) {
			listener();
		}
	}

	/**
	 * 获取当前主题偏好
	 */
	getTheme(): Theme {
		return this.theme;
	}

	/**
	 * 获取当前有效主题（light 或 dark）
	 */
	getEffectiveTheme(): EffectiveTheme {
		return this.effectiveTheme;
	}

	/**
	 * 设置主题偏好
	 */
	setTheme(theme: Theme): void {
		this.theme = theme;
		localStorage.setItem(STORAGE_KEY, theme);

		const newEffectiveTheme = this.computeEffectiveTheme();
		if (newEffectiveTheme !== this.effectiveTheme) {
			this.effectiveTheme = newEffectiveTheme;
		}

		this.notifyListeners();
	}

	/**
	 * 切换主题（light <-> dark）
	 * 注意：仅在 light 和 dark 之间切换，不涉及 system
	 */
	toggleTheme(): void {
		const newTheme = this.effectiveTheme === "light" ? "dark" : "light";
		this.setTheme(newTheme);
	}

	/**
	 * 订阅主题变化
	 */
	subscribe(listener: () => void): () => void {
		this.listeners.add(listener);
		return () => {
			this.listeners.delete(listener);
		};
	}

	/**
	 * 清理资源
	 */
	destroy(): void {
		if (this.mediaQuery) {
			this.mediaQuery.removeEventListener(
				"change",
				this.handleSystemThemeChange,
			);
		}
		this.listeners.clear();
	}
}

// 单例实例
export const themeManager = new ThemeManager();
