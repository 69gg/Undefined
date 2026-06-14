import { describe, expect, it } from "vitest";
import type { Attachment } from "../runtime-client/types";
import {
	extractAttachmentTags,
	renderAttachmentPlaceholders,
	resolveAttachmentUrl,
} from "./AttachmentProcessor";

describe("resolveAttachmentUrl", () => {
	it("相对路径 + runtimeUrl → 补上前缀", () => {
		expect(
			resolveAttachmentUrl(
				"/api/v1/chat/attachments/img-1/preview",
				"http://127.0.0.1:8788",
			),
		).toBe("http://127.0.0.1:8788/api/v1/chat/attachments/img-1/preview");
	});

	it("runtimeUrl 带尾斜杠时不产生双斜杠", () => {
		expect(
			resolveAttachmentUrl(
				"/api/v1/chat/attachments/img-1/preview",
				"http://127.0.0.1:8788/",
			),
		).toBe("http://127.0.0.1:8788/api/v1/chat/attachments/img-1/preview");
	});

	it("相对路径但无 runtimeUrl → 原样返回（降级）", () => {
		expect(resolveAttachmentUrl("/api/v1/chat/attachments/img-1/preview")).toBe(
			"/api/v1/chat/attachments/img-1/preview",
		);
	});

	it("http/https 绝对地址 → 原样返回（不重复前缀）", () => {
		expect(
			resolveAttachmentUrl("http://example.com/x.png", "http://127.0.0.1:8788"),
		).toBe("http://example.com/x.png");
		expect(
			resolveAttachmentUrl(
				"https://example.com/x.png",
				"http://127.0.0.1:8788",
			),
		).toBe("https://example.com/x.png");
	});

	it("data:/blob:/协议相对 → 原样返回", () => {
		expect(resolveAttachmentUrl("data:image/png;base64,AAAA")).toBe(
			"data:image/png;base64,AAAA",
		);
		expect(resolveAttachmentUrl("blob:abc-123")).toBe("blob:abc-123");
		expect(
			resolveAttachmentUrl("//cdn.example.com/x.png", "http://127.0.0.1:8788"),
		).toBe("//cdn.example.com/x.png");
	});

	it("空/null/undefined/空白 → 空字符串", () => {
		expect(resolveAttachmentUrl("")).toBe("");
		expect(resolveAttachmentUrl(null)).toBe("");
		expect(resolveAttachmentUrl(undefined)).toBe("");
		expect(resolveAttachmentUrl("   ")).toBe("");
	});
});

describe("renderAttachmentPlaceholders", () => {
	const imageAttachment: Attachment = {
		id: "img-1",
		name: "chart.png",
		size: 2048,
		mediaType: "image/png",
		kind: "image",
		downloadUrl: "/api/v1/chat/attachments/img-1",
		previewUrl: "/api/v1/chat/attachments/img-1/preview",
		discarded: false,
	};

	it("正文 <attachment uid/> 图片以绝对 URL 渲染，且不含失效的旧端点", () => {
		const content = '<attachment uid="img-1"/>';
		const { cleanContent, attachmentUids } = extractAttachmentTags(content);
		const html = renderAttachmentPlaceholders(
			cleanContent,
			attachmentUids,
			[imageAttachment],
			"http://127.0.0.1:8788",
		);
		expect(html).toContain(
			'src="http://127.0.0.1:8788/api/v1/chat/attachments/img-1/preview"',
		);
		// 旧的、Runtime API 不存在的 fallback 端点不应再出现
		expect(html).not.toContain("/api/runtime/attachments/");
	});
});
