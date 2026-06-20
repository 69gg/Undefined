import { describe, expect, it } from "vitest";
import type { Attachment } from "../runtime-client/types";
import {
	extractAttachmentTags,
	findAttachmentByUid,
} from "./AttachmentProcessor";

describe("extractAttachmentTags", () => {
	it("提取 <attachment uid/> 为占位符并收集 UID（占位符以空行包裹）", () => {
		const { cleanContent, attachmentUids } = extractAttachmentTags(
			'看图<attachment uid="pic_1"/>结束',
		);
		expect(attachmentUids).toEqual(["pic_1"]);
		expect(cleanContent).toContain("\n\nATTACHMENT_PLACEHOLDER_0\n\n");
	});

	it("兼容 <pic uid/> 旧标签与多附件，序号与 UID 顺序对应", () => {
		const { attachmentUids } = extractAttachmentTags(
			'<attachment uid="pic_1"/><pic uid="pic_2"/>',
		);
		expect(attachmentUids).toEqual(["pic_1", "pic_2"]);
	});

	it("无附件标签时原样返回", () => {
		const { cleanContent, attachmentUids } = extractAttachmentTags("纯文本");
		expect(cleanContent).toBe("纯文本");
		expect(attachmentUids).toEqual([]);
	});
});

describe("findAttachmentByUid", () => {
	const att: Attachment = {
		id: "pic_1",
		name: "x.png",
		size: 1,
		mediaType: "image/png",
		kind: "image",
		downloadUrl: null,
		previewUrl: null,
		discarded: false,
	};

	it("按 UID 命中返回附件", () => {
		expect(findAttachmentByUid([att], "pic_1")).toBe(att);
	});

	it("未命中返回 null", () => {
		expect(findAttachmentByUid([att], "nope")).toBeNull();
	});
});
