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
	type MediaQueryListener = (event: MediaQueryListEvent) => void;
	type MutableMediaQueryList = MediaQueryList & {
		_setMatches: (matches: boolean) => void;
		_syncMatches: (matches: boolean) => void;
	};
	const queryLists = new Map<string, MutableMediaQueryList>();
	const computeMatches = (query: string): boolean => {
		const maxWidth = /max-width:\s*(\d+)px/.exec(query);
		return maxWidth ? window.innerWidth <= Number(maxWidth[1]) : false;
	};
	const makeQueryList = (query: string): MutableMediaQueryList => {
		let matches = computeMatches(query);
		const listeners = new Set<MediaQueryListener>();
		const mql = {
			get matches() {
				return matches;
			},
			media: query,
			onchange: null,
			addEventListener: (
				_type: string,
				listener: EventListenerOrEventListenerObject,
			) => {
				listeners.add(listener as MediaQueryListener);
			},
			removeEventListener: (
				_type: string,
				listener: EventListenerOrEventListenerObject,
			) => {
				listeners.delete(listener as MediaQueryListener);
			},
			addListener: (listener: MediaQueryListener) => {
				listeners.add(listener);
			},
			removeListener: (listener: MediaQueryListener) => {
				listeners.delete(listener);
			},
			dispatchEvent: () => false,
			_syncMatches(nextMatches: boolean) {
				matches = nextMatches;
			},
			_setMatches(nextMatches: boolean) {
				if (matches === nextMatches) {
					return;
				}
				matches = nextMatches;
				const event = { matches, media: query } as MediaQueryListEvent;
				for (const listener of listeners) {
					listener(event);
				}
				mql.onchange?.(event);
			},
		} as MutableMediaQueryList;
		return mql;
	};

	Object.defineProperty(window, "matchMedia", {
		writable: true,
		configurable: true,
		value: (query: string): MediaQueryList => {
			const existing = queryLists.get(query);
			if (existing) {
				existing._syncMatches(computeMatches(query));
				return existing;
			}
			const created = makeQueryList(query);
			queryLists.set(query, created);
			return created;
		},
	});
	window.addEventListener("resize", () => {
		for (const [query, mql] of queryLists) {
			mql._setMatches(computeMatches(query));
		}
	});
}

// jsdom 未实现 URL.createObjectURL/revokeObjectURL：图片附件经 blob URL 渲染需要它们，
// 提供轻量 mock（返回唯一 blob: URL，revoke 为 no-op）。
if (!URL.createObjectURL) {
	let blobUrlCounter = 0;
	URL.createObjectURL = vi.fn(() => `blob:mock-${++blobUrlCounter}`);
	URL.revokeObjectURL = vi.fn();
}
