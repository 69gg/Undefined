import { screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { ImageViewerModal } from "./ImageViewerModal";

describe("ImageViewerModal", () => {
	it("当 imageViewer 为 null 时不渲染", () => {
		const { container } = renderWithProviders(
			<ImageViewerModal imageViewer={null} onClose={vi.fn()} />,
		);
		expect(container.firstChild).toBeNull();
	});

	it("当 imageViewer.open 为 false 时不渲染", () => {
		const { container } = renderWithProviders(
			<ImageViewerModal
				imageViewer={{ open: false, src: "", alt: "" }}
				onClose={vi.fn()}
			/>,
		);
		expect(container.firstChild).toBeNull();
	});

	it("当 imageViewer.open 为 true 时渲染图片", () => {
		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={vi.fn()}
			/>,
		);

		const img = screen.getByRole("img");
		expect(img).toBeInTheDocument();
		expect(img).toHaveAttribute("src", "https://example.com/image.jpg");
		expect(img).toHaveAttribute("alt", "测试图片");
	});

	it("点击背景应该关闭查看器", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();

		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={onClose}
			/>,
		);

		const dialog = screen.getByRole("dialog");
		await user.click(dialog);

		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it("点击图片不应该关闭查看器", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();

		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={onClose}
			/>,
		);

		const img = screen.getByRole("img");
		await user.click(img);

		expect(onClose).not.toHaveBeenCalled();
	});

	it("点击关闭按钮应该关闭查看器", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();

		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={onClose}
			/>,
		);

		const closeButton = screen.getByLabelText("关闭");
		await user.click(closeButton);

		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it("按 ESC 键应该关闭查看器", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();

		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={onClose}
			/>,
		);

		await user.keyboard("{Escape}");

		expect(onClose).toHaveBeenCalledTimes(1);
	});

	it("应该有正确的可访问性属性", () => {
		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={vi.fn()}
			/>,
		);

		const dialog = screen.getByRole("dialog");
		expect(dialog).toHaveAttribute("aria-modal", "true");
		expect(dialog).toHaveAttribute("aria-label", "图片查看器");
	});

	it("支持缩放、旋转和重置", async () => {
		const user = userEvent.setup();
		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={vi.fn()}
			/>,
		);

		const img = screen.getByRole("img");
		await user.click(screen.getByRole("button", { name: "放大" }));
		expect(img).toHaveStyle({ transform: "scale(1.25) rotate(0deg)" });

		await user.click(screen.getByRole("button", { name: "旋转" }));
		expect(img).toHaveStyle({ transform: "scale(1.25) rotate(90deg)" });

		await user.click(screen.getByRole("button", { name: "重置" }));
		expect(img).toHaveStyle({ transform: "scale(1) rotate(0deg)" });
	});

	it("渲染可滚动查看区域以支持放大后查看图片边缘", () => {
		renderWithProviders(
			<ImageViewerModal
				imageViewer={{
					open: true,
					src: "https://example.com/image.jpg",
					alt: "测试图片",
				}}
				onClose={vi.fn()}
			/>,
		);

		expect(document.querySelector(".runtime-image-viewer-stage")).toBeTruthy();
	});
});
