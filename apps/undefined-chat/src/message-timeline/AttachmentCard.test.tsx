import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { AttachmentImageProvider } from "../rendering/AttachmentImageContext";
import type {
	Attachment,
	AttachmentPreviewResult,
} from "../runtime-client/types";
import { AttachmentCard } from "./AttachmentCard";

function imageResult(): AttachmentPreviewResult {
	return {
		status: 200,
		ok: true,
		mediaType: "image/png",
		bytes: [137, 80, 78, 71],
		body: null,
	};
}

function renderWithProvider(
	ui: ReactNode,
	previewImpl?: () => Promise<AttachmentPreviewResult>,
) {
	const previewAttachment = vi.fn(previewImpl ?? (async () => imageResult()));
	return {
		previewAttachment,
		...render(
			<AttachmentImageProvider client={{ previewAttachment }}>
				{ui}
			</AttachmentImageProvider>,
		),
	};
}

describe("AttachmentCard", () => {
	const mockImageAttachment: Attachment = {
		id: "img-1",
		name: "test-image.png",
		size: 1024 * 100, // 100KB
		mediaType: "image/png",
		kind: "image",
		downloadUrl: "http://example.com/download/img-1",
		previewUrl: "http://example.com/preview/img-1",
		discarded: false,
	};

	const mockLargeImageAttachment: Attachment = {
		id: "img-2",
		name: "large-image.jpg",
		size: 15 * 1024 * 1024, // 15MB (> 12MB threshold)
		mediaType: "image/jpeg",
		kind: "image",
		downloadUrl: "http://example.com/download/img-2",
		previewUrl: "http://example.com/preview/img-2",
		discarded: false,
	};

	const mockFileAttachment: Attachment = {
		id: "file-1",
		name: "document.pdf",
		size: 1024 * 1024 * 2.5, // 2.5MB
		mediaType: "application/pdf",
		kind: "file",
		downloadUrl: "http://example.com/download/file-1",
		previewUrl: null,
		discarded: false,
	};

	describe("图片附件", () => {
		it("小图片内联显示为 blob 图片", async () => {
			renderWithProvider(<AttachmentCard attachment={mockImageAttachment} />);

			const img = await screen.findByAltText("test-image.png");
			expect(img).toHaveClass("runtime-chat-image");
			expect(img.getAttribute("src")).toMatch(/^blob:/);
			expect(img).toHaveAttribute("loading", "lazy");
		});

		it("点击内联图片回传 blob URL 给 onOpenImage", async () => {
			const onOpenImage = vi.fn();
			renderWithProvider(
				<AttachmentCard
					attachment={mockImageAttachment}
					onOpenImage={onOpenImage}
				/>,
			);

			const img = await screen.findByAltText("test-image.png");
			fireEvent.click(img);

			expect(onOpenImage).toHaveBeenCalledWith(
				expect.stringMatching(/^blob:/),
				"test-image.png",
			);
		});

		it("图片加载失败时降级为文件图标", async () => {
			renderWithProvider(
				<AttachmentCard attachment={mockImageAttachment} />,
				async () => ({
					status: 415,
					ok: false,
					mediaType: null,
					bytes: [],
					body: "x",
				}),
			);

			expect(await screen.findByText("IMG")).toBeInTheDocument();
		});

		it("大图片（>12MB）显示为文件卡片", () => {
			renderWithProvider(
				<AttachmentCard
					attachment={mockLargeImageAttachment}
					onPreview={vi.fn()}
				/>,
			);

			expect(screen.getByText("large-image.jpg")).toBeInTheDocument();
			expect(screen.getByText("15 MB")).toBeInTheDocument();
			expect(screen.getByRole("button", { name: "预览" })).toBeInTheDocument();
		});

		it("大图片文件卡片缩略图以 blob 渲染", async () => {
			const { container } = renderWithProvider(
				<AttachmentCard
					attachment={mockLargeImageAttachment}
					onPreview={vi.fn()}
				/>,
			);

			const thumb = await waitFor(() => {
				const el = container.querySelector("img.runtime-chat-attachment-thumb");
				if (!el) throw new Error("thumbnail not loaded");
				return el;
			});
			expect(thumb.getAttribute("src")).toMatch(/^blob:/);
		});
	});

	describe("文件附件", () => {
		it("应该显示文件卡片布局", () => {
			renderWithProvider(
				<AttachmentCard attachment={mockFileAttachment} onDownload={vi.fn()} />,
			);

			expect(screen.getByText("document.pdf")).toBeInTheDocument();
			expect(screen.getByText("2.5 MB")).toBeInTheDocument();
			expect(screen.getByText("PDF")).toBeInTheDocument();
		});

		it("点击下载按钮应该触发下载回调", async () => {
			const user = userEvent.setup();
			const onDownload = vi.fn();
			renderWithProvider(
				<AttachmentCard
					attachment={mockFileAttachment}
					onDownload={onDownload}
				/>,
			);

			await user.click(screen.getByRole("button", { name: "下载" }));

			expect(onDownload).toHaveBeenCalledWith(mockFileAttachment);
		});
	});

	describe("可选回调", () => {
		it("没有 onOpenImage 时内联图片不可点击（非 button 角色）", async () => {
			renderWithProvider(<AttachmentCard attachment={mockImageAttachment} />);

			const img = await screen.findByAltText("test-image.png");
			expect(img).not.toHaveAttribute("role", "button");
		});

		it("没有 onDownload 时不显示下载按钮", () => {
			renderWithProvider(<AttachmentCard attachment={mockFileAttachment} />);

			expect(
				screen.queryByRole("button", { name: "下载" }),
			).not.toBeInTheDocument();
		});

		it("图片文件卡片没有 onPreview 时不显示预览按钮", () => {
			renderWithProvider(
				<AttachmentCard
					attachment={mockLargeImageAttachment}
					onDownload={vi.fn()}
				/>,
			);

			expect(
				screen.queryByRole("button", { name: "预览" }),
			).not.toBeInTheDocument();
			expect(screen.getByRole("button", { name: "下载" })).toBeInTheDocument();
		});
	});

	describe("边界情况", () => {
		it("0 字节文件应该正确显示", () => {
			renderWithProvider(
				<AttachmentCard
					attachment={{ ...mockFileAttachment, size: 0 }}
					onDownload={vi.fn()}
				/>,
			);

			expect(screen.getByText("0 B")).toBeInTheDocument();
		});

		it("超长文件名应该被截断", () => {
			const longName = `${"a".repeat(200)}.pdf`;
			renderWithProvider(
				<AttachmentCard
					attachment={{ ...mockFileAttachment, name: longName }}
					onDownload={vi.fn()}
				/>,
			);

			const nameElement = screen.getByText(longName);
			expect(nameElement).toHaveStyle({
				overflow: "hidden",
				textOverflow: "ellipsis",
				whiteSpace: "nowrap",
			});
		});
	});
});
