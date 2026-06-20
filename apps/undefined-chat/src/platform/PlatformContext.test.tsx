import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
	PlatformProvider,
	isAndroidPlatform,
	isDesktopPlatform,
	isMobilePlatform,
	usePlatform,
} from "./PlatformContext";
import type { PlatformInfo } from "./types";

// Mock Tauri invoke
vi.mock("@tauri-apps/api/core", () => ({
	invoke: vi.fn(),
}));

const { invoke } = await import("@tauri-apps/api/core");

describe("PlatformContext", () => {
	it("提供默认平台信息", () => {
		function TestComponent() {
			const platform = usePlatform();
			return <div data-testid="platform-os">{platform.os}</div>;
		}

		render(
			<PlatformProvider>
				<TestComponent />
			</PlatformProvider>,
		);

		// 初始状态应该是 unknown
		expect(screen.getByTestId("platform-os")).toHaveTextContent("unknown");
	});

	it("从 Tauri 命令获取平台信息", async () => {
		const mockPlatform: PlatformInfo = {
			os: "linux",
			family: "unix",
			arch: "x86_64",
			debug: false,
			supportsSystemKeyring: true,
			supportsSecureApiKeyStorage: true,
			supportsSse: true,
			supportsHtmlPreview: true,
		};

		vi.mocked(invoke).mockResolvedValueOnce(mockPlatform);

		function TestComponent() {
			const platform = usePlatform();
			return (
				<div>
					<div data-testid="platform-os">{platform.os}</div>
					<div data-testid="platform-arch">{platform.arch}</div>
					<div data-testid="supports-keyring">
						{String(platform.supportsSystemKeyring)}
					</div>
				</div>
			);
		}

		render(
			<PlatformProvider>
				<TestComponent />
			</PlatformProvider>,
		);

		await waitFor(() => {
			expect(screen.getByTestId("platform-os")).toHaveTextContent("linux");
		});

		expect(screen.getByTestId("platform-arch")).toHaveTextContent("x86_64");
		expect(screen.getByTestId("supports-keyring")).toHaveTextContent("true");
	});

	it("Tauri 失败时使用浏览器回退检测", async () => {
		vi.mocked(invoke).mockRejectedValueOnce(new Error("Tauri not available"));

		// 模拟 Android userAgent
		Object.defineProperty(navigator, "userAgent", {
			value: "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
			configurable: true,
		});

		function TestComponent() {
			const platform = usePlatform();
			return <div data-testid="platform-os">{platform.os}</div>;
		}

		render(
			<PlatformProvider>
				<TestComponent />
			</PlatformProvider>,
		);

		await waitFor(() => {
			expect(screen.getByTestId("platform-os")).toHaveTextContent("android");
		});
	});

	it("区分系统密钥链和安全 API Key 存储能力", async () => {
		const mockPlatform: PlatformInfo = {
			os: "android",
			family: "unix",
			arch: "aarch64",
			debug: false,
			supportsSystemKeyring: false,
			supportsSecureApiKeyStorage: true,
			supportsSse: true,
			supportsHtmlPreview: true,
		};
		vi.mocked(invoke).mockResolvedValueOnce(mockPlatform);

		function TestComponent() {
			const platform = usePlatform();
			return (
				<div>
					<div data-testid="supports-keyring">
						{String(platform.supportsSystemKeyring)}
					</div>
					<div data-testid="supports-secure-api-key">
						{String(platform.supportsSecureApiKeyStorage)}
					</div>
				</div>
			);
		}

		render(
			<PlatformProvider>
				<TestComponent />
			</PlatformProvider>,
		);

		await waitFor(() => {
			expect(screen.getByTestId("supports-secure-api-key")).toHaveTextContent(
				"true",
			);
		});
		expect(screen.getByTestId("supports-keyring")).toHaveTextContent("false");
	});

	it("处理 Tauri 调用错误", async () => {
		const consoleWarnSpy = vi
			.spyOn(console, "warn")
			.mockImplementation(() => {});
		vi.mocked(invoke).mockRejectedValueOnce(new Error("Network error"));

		function TestComponent() {
			const platform = usePlatform();
			return <div data-testid="platform-os">{platform.os}</div>;
		}

		render(
			<PlatformProvider>
				<TestComponent />
			</PlatformProvider>,
		);

		await waitFor(() => {
			expect(consoleWarnSpy).toHaveBeenCalled();
		});

		consoleWarnSpy.mockRestore();
	});
});

describe("平台判断工具函数", () => {
	it("isAndroidPlatform 正确识别 Android", () => {
		expect(
			isAndroidPlatform({
				os: "android",
				family: "unix",
				arch: "aarch64",
				debug: false,
				supportsSystemKeyring: false,
				supportsSecureApiKeyStorage: false,
				supportsSse: true,
				supportsHtmlPreview: false,
			}),
		).toBe(true);

		expect(
			isAndroidPlatform({
				os: "linux",
				family: "unix",
				arch: "x86_64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: true,
			}),
		).toBe(false);
	});

	it("isDesktopPlatform 正确识别桌面平台", () => {
		expect(
			isDesktopPlatform({
				os: "windows",
				family: "windows",
				arch: "x86_64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: true,
			}),
		).toBe(true);

		expect(
			isDesktopPlatform({
				os: "macos",
				family: "unix",
				arch: "aarch64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: true,
			}),
		).toBe(true);

		expect(
			isDesktopPlatform({
				os: "linux",
				family: "unix",
				arch: "x86_64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: true,
			}),
		).toBe(true);

		expect(
			isDesktopPlatform({
				os: "android",
				family: "unix",
				arch: "aarch64",
				debug: false,
				supportsSystemKeyring: false,
				supportsSecureApiKeyStorage: false,
				supportsSse: true,
				supportsHtmlPreview: false,
			}),
		).toBe(false);
	});

	it("isMobilePlatform 正确识别移动平台", () => {
		expect(
			isMobilePlatform({
				os: "android",
				family: "unix",
				arch: "aarch64",
				debug: false,
				supportsSystemKeyring: false,
				supportsSecureApiKeyStorage: false,
				supportsSse: true,
				supportsHtmlPreview: false,
			}),
		).toBe(true);

		expect(
			isMobilePlatform({
				os: "ios",
				family: "unix",
				arch: "aarch64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: false,
			}),
		).toBe(true);

		expect(
			isMobilePlatform({
				os: "linux",
				family: "unix",
				arch: "x86_64",
				debug: false,
				supportsSystemKeyring: true,
				supportsSecureApiKeyStorage: true,
				supportsSse: true,
				supportsHtmlPreview: true,
			}),
		).toBe(false);
	});
});
