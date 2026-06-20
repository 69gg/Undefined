import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { ThemeToggle } from "./ThemeToggle";
import * as useThemeModule from "./use-theme";

// Mock useTheme hook
vi.mock("./use-theme", () => ({
	useTheme: vi.fn(),
}));

describe("ThemeToggle", () => {
	const mockToggleTheme = vi.fn();

	beforeEach(() => {
		vi.clearAllMocks();
	});

	test("renders moon icon in light mode", () => {
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "light",
			effectiveTheme: "light",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		renderWithProviders(<ThemeToggle />);

		expect(screen.getByLabelText("切换到暗色模式")).toBeInTheDocument();
		expect(screen.getByLabelText("月亮图标")).toBeInTheDocument();
	});

	test("renders sun icon in dark mode", () => {
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "dark",
			effectiveTheme: "dark",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		renderWithProviders(<ThemeToggle />);

		expect(screen.getByLabelText("切换到亮色模式")).toBeInTheDocument();
		expect(screen.getByLabelText("太阳图标")).toBeInTheDocument();
	});

	test("calls toggleTheme on click", async () => {
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "light",
			effectiveTheme: "light",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		renderWithProviders(<ThemeToggle />);

		const button = screen.getByRole("button");
		await userEvent.click(button);

		expect(mockToggleTheme).toHaveBeenCalledOnce();
	});

	test("button has correct accessibility attributes", () => {
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "light",
			effectiveTheme: "light",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		renderWithProviders(<ThemeToggle />);

		const button = screen.getByRole("button");
		expect(button).toHaveAttribute("type", "button");
		expect(button).toHaveAttribute("aria-label", "切换到暗色模式");
		expect(button).toHaveAttribute("title", "切换到暗色模式");
	});

	test("updates icon when theme changes", () => {
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "light",
			effectiveTheme: "light",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		const { rerender } = renderWithProviders(<ThemeToggle />);
		expect(screen.getByLabelText("月亮图标")).toBeInTheDocument();

		// 模拟主题切换
		vi.mocked(useThemeModule.useTheme).mockReturnValue({
			theme: "dark",
			effectiveTheme: "dark",
			setTheme: vi.fn(),
			toggleTheme: mockToggleTheme,
		});

		rerender(<ThemeToggle />);
		expect(screen.getByLabelText("太阳图标")).toBeInTheDocument();
	});
});
