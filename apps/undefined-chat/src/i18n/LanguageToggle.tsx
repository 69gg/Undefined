/**
 * 语言切换按钮组件
 * 在 zh-CN / en 之间切换，显示地球图标并标注目标语言。
 * 风格对齐 theme/ThemeToggle.tsx 的 icon-button。
 */

import { useTranslation } from "./index";

export function LanguageToggle() {
	const { locale, setLocale, t } = useTranslation();
	const nextLocale = locale === "zh-CN" ? "en" : "zh-CN";
	const label = t("language.toggle");

	return (
		<button
			type="button"
			className="icon-button language-toggle"
			onClick={() => setLocale(nextLocale)}
			aria-label={label}
			title={label}
		>
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
				aria-label={label}
			>
				<title>{label}</title>
				<circle cx="12" cy="12" r="10" />
				<line x1="2" y1="12" x2="22" y2="12" />
				<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
			</svg>
			<span className="language-toggle-text">
				{locale === "zh-CN" ? t("language.en") : t("language.zh")}
			</span>
		</button>
	);
}
