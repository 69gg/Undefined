import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { themeManager } from "./theme-manager";

describe("ThemeManager", () => {
	let mockMatchMedia: (query: string) => MediaQueryList;
	let darkModeListeners: ((event: MediaQueryListEvent) => void)[] = [];
	let isDarkMode = false;

	beforeEach(async () => {
		// Mock localStorage
		const storage: Record<string, string> = {};
		vi.spyOn(Storage.prototype, "getItem").mockImplementation(
			(key: string) => storage[key] || null,
		);
		vi.spyOn(Storage.prototype, "setItem").mockImplementation(
			(key: string, value: string) => {
				storage[key] = value;
			},
		);

		// Mock matchMedia
		darkModeListeners = [];
		isDarkMode = false;
		mockMatchMedia = (query: string) => {
			if (query === "(prefers-color-scheme: dark)") {
				return {
					matches: isDarkMode,
					addEventListener: vi.fn((event: string, handler: () => void) => {
						if (event === "change") {
							darkModeListeners.push(handler);
						}
					}),
					removeEventListener: vi.fn((event: string, handler: () => void) => {
						if (event === "change") {
							const index = darkModeListeners.indexOf(handler);
							if (index > -1) {
								darkModeListeners.splice(index, 1);
							}
						}
					}),
				} as unknown as MediaQueryList;
			}
			return {} as MediaQueryList;
		};
		vi.stubGlobal("matchMedia", mockMatchMedia);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	test("initializes with system theme by default", () => {
		expect(themeManager.getTheme()).toBeDefined();
		expect(themeManager.getEffectiveTheme()).toMatch(/^(light|dark)$/);
	});

	test("setTheme updates theme and persists to localStorage", () => {
		themeManager.setTheme("dark");

		expect(themeManager.getTheme()).toBe("dark");
		expect(themeManager.getEffectiveTheme()).toBe("dark");
		expect(localStorage.getItem("undefined-chat-theme")).toBe("dark");
	});

	test("setTheme notifies listeners", () => {
		const listener = vi.fn();
		const unsubscribe = themeManager.subscribe(listener);

		themeManager.setTheme("dark");
		expect(listener).toHaveBeenCalled();

		unsubscribe();
	});

	test("toggleTheme switches between light and dark", () => {
		themeManager.setTheme("light");

		themeManager.toggleTheme();
		expect(themeManager.getTheme()).toBe("dark");
		expect(themeManager.getEffectiveTheme()).toBe("dark");

		themeManager.toggleTheme();
		expect(themeManager.getTheme()).toBe("light");
		expect(themeManager.getEffectiveTheme()).toBe("light");
	});

	test("subscribe returns unsubscribe function", () => {
		const listener = vi.fn();
		const unsubscribe = themeManager.subscribe(listener);

		themeManager.setTheme("dark");
		expect(listener).toHaveBeenCalled();

		listener.mockClear();
		unsubscribe();
		themeManager.setTheme("light");
		expect(listener).not.toHaveBeenCalled();
	});

	test("handles different theme values", () => {
		themeManager.setTheme("light");
		expect(themeManager.getEffectiveTheme()).toBe("light");

		themeManager.setTheme("dark");
		expect(themeManager.getEffectiveTheme()).toBe("dark");

		themeManager.setTheme("system");
		expect(themeManager.getEffectiveTheme()).toMatch(/^(light|dark)$/);
	});
});
