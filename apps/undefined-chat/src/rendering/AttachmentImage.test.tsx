import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import type { AttachmentPreviewResult } from "../runtime-client/types";
import { AttachmentImage } from "./AttachmentImage";
import { AttachmentImageProvider } from "./AttachmentImageContext";

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
			<LanguageProvider>
				<AttachmentImageProvider client={{ previewAttachment }}>
					{ui}
				</AttachmentImageProvider>
			</LanguageProvider>,
		),
	};
}

describe("AttachmentImage", () => {
	// 固定为简体中文，使断言不受测试环境 navigator.language 影响
	beforeEach(() => {
		window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
	});

	it("加载成功显示 img（blob src）", async () => {
		renderWithProvider(<AttachmentImage uid="pic_1" alt="chart.png" />);

		const img = await screen.findByRole("img", { name: "chart.png" });
		expect(img.getAttribute("src")).toMatch(/^blob:/);
	});

	it("加载失败显示文件图标降级，不渲染 img", async () => {
		renderWithProvider(
			<AttachmentImage uid="pic_1" alt="chart.png" mediaType="image/png" />,
			async () => ({
				status: 415,
				ok: false,
				mediaType: null,
				bytes: [],
				body: "x",
			}),
		);

		expect(await screen.findByText("IMG")).toBeInTheDocument();
		expect(screen.queryByRole("img")).toBeNull();
	});

	it("点击已加载图片回传 blob URL 给 onOpenImage", async () => {
		const onOpenImage = vi.fn();
		renderWithProvider(
			<AttachmentImage uid="pic_1" alt="chart.png" onOpenImage={onOpenImage} />,
		);

		const img = await screen.findByAltText("chart.png");
		fireEvent.click(img);

		expect(onOpenImage).toHaveBeenCalledWith(
			expect.stringMatching(/^blob:/),
			"chart.png",
		);
	});
});
