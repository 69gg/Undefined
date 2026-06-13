import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Attachment } from "../runtime-client/types";
import { AttachmentCard } from "./AttachmentCard";

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
		it("小图片应该内联显示", () => {
			render(
				<AttachmentCard attachment={mockImageAttachment} onPreview={vi.fn()} />,
			);

			const img = screen.getByRole("img", { name: mockImageAttachment.name });
			expect(img).toBeInTheDocument();
			expect(img).toHaveClass("runtime-chat-image");
			expect(img).toHaveAttribute("src", mockImageAttachment.previewUrl);
			expect(img).toHaveAttribute("loading", "lazy");
		});

		it("点击内联图片应该触发预览", async () => {
			const user = userEvent.setup();
			const onPreview = vi.fn();
			render(
				<AttachmentCard
					attachment={mockImageAttachment}
					onPreview={onPreview}
				/>,
			);

			const button = screen.getByRole("button");
			await user.click(button);

			expect(onPreview).toHaveBeenCalledWith(mockImageAttachment);
		});

		it("大图片应该显示为文件卡片", () => {
			render(
				<AttachmentCard
					attachment={mockLargeImageAttachment}
					onPreview={vi.fn()}
				/>,
			);

			expect(screen.getByText("large-image.jpg")).toBeInTheDocument();
			expect(screen.getByText("15 MB")).toBeInTheDocument();
			expect(screen.getByRole("button", { name: "预览" })).toBeInTheDocument();
		});

		it("大图片应该显示缩略图", () => {
			render(
				<AttachmentCard
					attachment={mockLargeImageAttachment}
					onPreview={vi.fn()}
				/>,
			);

			const thumb = screen.getByAltText("");
			expect(thumb).toHaveClass("runtime-chat-attachment-thumb");
			expect(thumb).toHaveAttribute("src", mockLargeImageAttachment.previewUrl);
		});
	});

	describe("文件附件", () => {
		it("应该显示文件卡片布局", () => {
			render(
				<AttachmentCard attachment={mockFileAttachment} onDownload={vi.fn()} />,
			);

			expect(screen.getByText("document.pdf")).toBeInTheDocument();
			expect(screen.getByText("2.5 MB")).toBeInTheDocument();
			expect(screen.getByText("PDF")).toBeInTheDocument();
		});

		it("点击下载按钮应该触发下载回调", async () => {
			const user = userEvent.setup();
			const onDownload = vi.fn();
			render(
				<AttachmentCard
					attachment={mockFileAttachment}
					onDownload={onDownload}
				/>,
			);

			const downloadButton = screen.getByRole("button", { name: "下载" });
			await user.click(downloadButton);

			expect(onDownload).toHaveBeenCalledWith(mockFileAttachment);
		});

		it("应该显示正确的文件图标", () => {
			const testCases: Array<{
				mediaType: string;
				expectedIcon: string;
			}> = [
				{ mediaType: "image/png", expectedIcon: "IMG" },
				{ mediaType: "video/mp4", expectedIcon: "VID" },
				{ mediaType: "audio/mp3", expectedIcon: "AUD" },
				{ mediaType: "text/plain", expectedIcon: "TXT" },
				{ mediaType: "application/pdf", expectedIcon: "PDF" },
				{ mediaType: "application/zip", expectedIcon: "ZIP" },
				{ mediaType: "application/json", expectedIcon: "DAT" },
				{ mediaType: "application/octet-stream", expectedIcon: "FILE" },
			];

			for (const { mediaType, expectedIcon } of testCases) {
				const { unmount } = render(
					<AttachmentCard
						attachment={{ ...mockFileAttachment, mediaType, previewUrl: null }}
					/>,
				);
				expect(screen.getByText(expectedIcon)).toBeInTheDocument();
				unmount();
			}
		});
	});

	describe("可选回调", () => {
		it("没有 onPreview 时内联图片不应该可点击", () => {
			render(<AttachmentCard attachment={mockImageAttachment} />);

			const wrapper = screen.getByRole("button");
			expect(wrapper).toHaveStyle({ cursor: "default" });
		});

		it("没有 onDownload 时不应该显示下载按钮", () => {
			render(<AttachmentCard attachment={mockFileAttachment} />);

			expect(
				screen.queryByRole("button", { name: "下载" }),
			).not.toBeInTheDocument();
		});

		it("图片文件卡片没有 onPreview 时不应该显示预览按钮", () => {
			render(
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
		it("没有预览 URL 的图片应该显示图标", () => {
			const noPreviewImage: Attachment = {
				...mockImageAttachment,
				previewUrl: null,
			};
			render(<AttachmentCard attachment={noPreviewImage} />);

			expect(screen.getByText("IMG")).toBeInTheDocument();
		});

		it("0 字节文件应该正确显示", () => {
			render(
				<AttachmentCard
					attachment={{ ...mockFileAttachment, size: 0 }}
					onDownload={vi.fn()}
				/>,
			);

			expect(screen.getByText("0 B")).toBeInTheDocument();
		});

		it("超长文件名应该被截断", () => {
			const longName = `${"a".repeat(200)}.pdf`;
			render(
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
