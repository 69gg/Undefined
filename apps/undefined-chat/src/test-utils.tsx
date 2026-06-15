import {
	type RenderOptions,
	type RenderResult,
	render,
} from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { LOCALE_STORAGE_KEY, LanguageProvider, type Locale } from "./i18n";

/**
 * 测试包裹器：提供 LanguageProvider，使组件内 useTranslation 可用。
 */
function LanguageWrapper({ children }: { children: ReactNode }) {
	return <LanguageProvider>{children}</LanguageProvider>;
}

/**
 * 渲染并包裹 {@link LanguageProvider}，默认锁定 `zh-CN` locale。
 *
 * jsdom 默认 `navigator.language=en-US`，LanguageProvider 会回退到 `en`，
 * 导致现有中文文案断言失效；故渲染前显式写入 localStorage 锁定语言。
 * 需要测试英文时传入 `locale="en"`。
 *
 * 返回值与 `@testing-library/react` 的 `render` 一致（含 rerender，会保留同一 wrapper）。
 */
export function renderWithProviders(
	ui: ReactElement,
	options?: Omit<RenderOptions, "wrapper">,
	locale: Locale = "zh-CN",
): RenderResult {
	window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
	return render(ui, { wrapper: LanguageWrapper, ...options });
}
