import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { useTheme } from "./use-theme";

// Mock themeManager
vi.mock("./theme-manager", () => {
	let theme: "light" | "dark" | "system" = "system";
	let effectiveTheme: "light" | "dark" = "light";
	const listeners = new Set<() => void>();

	return {
		themeManager: {
			getTheme: () => theme,
			getEffectiveTheme: () => effectiveTheme,
			setTheme: vi.fn((newTheme: "light" | "dark" | "system") => {
				theme = newTheme;
				if (newTheme === "light") effectiveTheme = "light";
				if (newTheme === "dark") effectiveTheme = "dark";
				for (const listener of listeners) {
					listener();
				}
			}),
			toggleTheme: vi.fn(() => {
				theme = effectiveTheme === "light" ? "dark" : "light";
				effectiveTheme = effectiveTheme === "light" ? "dark" : "light";
				for (const listener of listeners) {
					listener();
				}
			}),
			subscribe: vi.fn((callback: () => void) => {
				listeners.add(callback);
				return () => {
					listeners.delete(callback);
				};
			}),
		},
	};
});

describe("useTheme", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	test("returns current theme state", () => {
		const { result } = renderHook(() => useTheme());

		expect(result.current.theme).toBeDefined();
		expect(result.current.effectiveTheme).toBeDefined();
		expect(typeof result.current.setTheme).toBe("function");
		expect(typeof result.current.toggleTheme).toBe("function");
	});

	test("setTheme updates theme", async () => {
		const { result } = renderHook(() => useTheme());

		result.current.setTheme("dark");

		await waitFor(() => {
			expect(result.current.effectiveTheme).toBe("dark");
		});
	});

	test("toggleTheme switches between themes", async () => {
		const { result } = renderHook(() => useTheme());

		const initialTheme = result.current.effectiveTheme;
		result.current.toggleTheme();

		await waitFor(() => {
			expect(result.current.effectiveTheme).not.toBe(initialTheme);
		});
	});

	test("subscribes to theme changes", async () => {
		renderHook(() => useTheme());
		const { themeManager } = await import("./theme-manager");

		expect(themeManager.subscribe).toHaveBeenCalled();
	});

	test("returns consistent structure across re-renders", () => {
		const { result, rerender } = renderHook(() => useTheme());

		const initialTheme = result.current.theme;
		const initialEffectiveTheme = result.current.effectiveTheme;

		rerender();

		// 结构保持一致
		expect(result.current.theme).toBe(initialTheme);
		expect(result.current.effectiveTheme).toBe(initialEffectiveTheme);
		expect(typeof result.current.setTheme).toBe("function");
		expect(typeof result.current.toggleTheme).toBe("function");
	});
});
