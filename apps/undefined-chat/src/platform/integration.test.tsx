import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DesktopLayout } from "./DesktopLayout";
import { PlatformProvider, usePlatform } from "./PlatformContext";
import { DEFAULT_PLATFORM_INFO } from "./types";

describe("Platform Integration", () => {
	it("DesktopLayout 应该正常渲染子组件", () => {
		const { getByText } = render(
			<DesktopLayout>
				<div>测试内容</div>
			</DesktopLayout>,
		);
		expect(getByText("测试内容")).toBeDefined();
	});

	it("DesktopLayout 应该应用 desktop-layout 类名", () => {
		const { container } = render(
			<DesktopLayout>
				<div>内容</div>
			</DesktopLayout>,
		);
		const layout = container.querySelector(".desktop-layout");
		expect(layout).toBeDefined();
	});

	it("DesktopLayout 应该支持自定义标题栏选项", () => {
		const { container } = render(
			<DesktopLayout enableCustomTitleBar={true}>
				<div>内容</div>
			</DesktopLayout>,
		);
		const layout = container.querySelector('[data-custom-titlebar="true"]');
		expect(layout).toBeDefined();
	});

	it("在组件中使用 usePlatform 进行条件渲染", () => {
		function PlatformAwareComponent() {
			const platform = usePlatform();

			return (
				<div>
					<div data-testid="os">{platform.os}</div>
					{platform.os === "android" && (
						<div data-testid="mobile-ui">移动端 UI</div>
					)}
					{["windows", "macos", "linux"].includes(platform.os) && (
						<div data-testid="desktop-ui">桌面端 UI</div>
					)}
					{platform.supportsSystemKeyring && (
						<div data-testid="keyring-notice">支持系统密钥链</div>
					)}
				</div>
			);
		}

		render(
			<PlatformProvider>
				<PlatformAwareComponent />
			</PlatformProvider>,
		);

		// 默认状态下应该显示 unknown
		expect(screen.getByTestId("os")).toHaveTextContent("unknown");
	});

	it("根据平台信息显示不同快捷键提示", () => {
		function KeybindingHint() {
			const platform = usePlatform();
			const modifier = platform.os === "macos" ? "Cmd" : "Ctrl";

			return (
				<div>
					<kbd data-testid="shortcut">{modifier}+K</kbd>
				</div>
			);
		}

		// 测试默认平台
		render(
			<PlatformProvider>
				<KeybindingHint />
			</PlatformProvider>,
		);

		// 默认应该显示 Ctrl（因为默认 os 是 unknown）
		expect(screen.getByTestId("shortcut")).toHaveTextContent("Ctrl+K");
	});

	it("根据平台能力启用/禁用功能", () => {
		function FeatureToggle() {
			const platform = usePlatform();

			return (
				<div>
					{platform.supportsSse ? (
						<div data-testid="sse-enabled">使用 SSE 流式传输</div>
					) : (
						<div data-testid="polling-fallback">使用轮询模式</div>
					)}
					{platform.supportsHtmlPreview && (
						<button type="button" data-testid="preview-btn">
							预览
						</button>
					)}
				</div>
			);
		}

		render(
			<PlatformProvider>
				<FeatureToggle />
			</PlatformProvider>,
		);

		// 默认平台支持 SSE
		expect(screen.getByTestId("sse-enabled")).toBeInTheDocument();
		// 默认平台不支持 HTML 预览
		expect(screen.queryByTestId("preview-btn")).not.toBeInTheDocument();
	});

	it("嵌套组件可以访问平台上下文", () => {
		function ParentComponent() {
			return (
				<div>
					<ChildComponent />
				</div>
			);
		}

		function ChildComponent() {
			const platform = usePlatform();
			return (
				<div>
					<GrandchildComponent />
					<div data-testid="child-os">{platform.os}</div>
				</div>
			);
		}

		function GrandchildComponent() {
			const platform = usePlatform();
			return <div data-testid="grandchild-arch">{platform.arch}</div>;
		}

		render(
			<PlatformProvider>
				<ParentComponent />
			</PlatformProvider>,
		);

		expect(screen.getByTestId("child-os")).toHaveTextContent(
			DEFAULT_PLATFORM_INFO.os,
		);
		expect(screen.getByTestId("grandchild-arch")).toHaveTextContent(
			DEFAULT_PLATFORM_INFO.arch,
		);
	});
});
