import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Mock Tauri API
vi.mock("@tauri-apps/api/core", () => ({
	invoke: vi.fn().mockResolvedValue({
		os: "linux",
		arch: "x86_64",
		version: "test",
	}),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

// jsdom 未实现 scrollIntoView：命令面板键盘导航会调用它，提供 no-op 避免报错。
if (!Element.prototype.scrollIntoView) {
	Element.prototype.scrollIntoView = () => {};
}

// jsdom 未实现 matchMedia：提供基于 window.innerWidth 的轻量实现，
// 让 useMediaQuery 等在测试中可用（支持设置 innerWidth 模拟移动端视口）。
// 仅解析 max-width，其余查询（如 prefers-color-scheme）返回 false，保持默认浅色主题。
if (!window.matchMedia) {
	Object.defineProperty(window, "matchMedia", {
		writable: true,
		configurable: true,
		value: (query: string): MediaQueryList => {
			const maxWidth = /max-width:\s*(\d+)px/.exec(query);
			const matches = maxWidth
				? window.innerWidth <= Number(maxWidth[1])
				: false;
			return {
				matches,
				media: query,
				onchange: null,
				addEventListener: () => {},
				removeEventListener: () => {},
				addListener: () => {},
				removeListener: () => {},
				dispatchEvent: () => false,
			} as MediaQueryList;
		},
	});
}
