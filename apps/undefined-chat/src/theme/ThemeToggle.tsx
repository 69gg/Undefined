/**
 * 主题切换按钮组件
 * 显示月亮（亮色模式）或太阳（暗色模式）图标
 */

import { useTranslation } from "../i18n";
import { useTheme } from "./use-theme";

export function ThemeToggle() {
	const { effectiveTheme, toggleTheme } = useTheme();
	const { t } = useTranslation();
	const toggleLabel =
		effectiveTheme === "light" ? t("theme.toDark") : t("theme.toLight");

	return (
		<button
			type="button"
			className="icon-button theme-toggle"
			onClick={toggleTheme}
			aria-label={toggleLabel}
			title={toggleLabel}
		>
			{effectiveTheme === "light" ? (
				// 月亮图标（亮色模式下显示）
				<svg
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					strokeWidth="2"
					strokeLinecap="round"
					strokeLinejoin="round"
					role="img"
					aria-label={t("theme.moonIcon")}
				>
					<title>{t("theme.toDark")}</title>
					<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
				</svg>
			) : (
				// 太阳图标（暗色模式下显示）
				<svg
					width="18"
					height="18"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					strokeWidth="2"
					strokeLinecap="round"
					strokeLinejoin="round"
					role="img"
					aria-label={t("theme.sunIcon")}
				>
					<title>{t("theme.toLight")}</title>
					<circle cx="12" cy="12" r="5" />
					<line x1="12" y1="1" x2="12" y2="3" />
					<line x1="12" y1="21" x2="12" y2="23" />
					<line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
					<line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
					<line x1="1" y1="12" x2="3" y2="12" />
					<line x1="21" y1="12" x2="23" y2="12" />
					<line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
					<line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
				</svg>
			)}
		</button>
	);
}
