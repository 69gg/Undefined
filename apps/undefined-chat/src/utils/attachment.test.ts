import { describe, expect, it } from "vitest";
import type { Attachment } from "../runtime-client/types";
import { isImageAttachment } from "./attachment";

function attachment(overrides: Partial<Attachment> = {}): Attachment {
	return {
		id: "att-1",
		name: "file",
		size: 0,
		mediaType: "application/octet-stream",
		kind: "file",
		downloadUrl: null,
		previewUrl: null,
		discarded: false,
		...overrides,
	};
}

describe("isImageAttachment", () => {
	it("returns true when kind is image regardless of mediaType", () => {
		expect(
			isImageAttachment(
				attachment({ kind: "image", mediaType: "application/octet-stream" }),
			),
		).toBe(true);
	});

	it("returns true for image/* media types", () => {
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "image/png" })),
		).toBe(true);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "image/jpeg" })),
		).toBe(true);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "image/gif" })),
		).toBe(true);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "image/webp" })),
		).toBe(true);
		expect(
			isImageAttachment(
				attachment({ kind: "file", mediaType: "image/svg+xml" }),
			),
		).toBe(true);
	});

	it("returns true when both kind and mediaType indicate an image", () => {
		expect(
			isImageAttachment(attachment({ kind: "image", mediaType: "image/png" })),
		).toBe(true);
	});

	it("returns false for non-image media types", () => {
		expect(
			isImageAttachment(
				attachment({ kind: "file", mediaType: "application/pdf" }),
			),
		).toBe(false);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "text/plain" })),
		).toBe(false);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "video/mp4" })),
		).toBe(false);
		expect(
			isImageAttachment(attachment({ kind: "file", mediaType: "audio/mpeg" })),
		).toBe(false);
	});

	it("returns false for empty or unknown mediaType when kind is not image", () => {
		expect(isImageAttachment(attachment({ kind: "file", mediaType: "" }))).toBe(
			false,
		);
		expect(
			isImageAttachment(attachment({ kind: "unknown", mediaType: "unknown" })),
		).toBe(false);
	});

	it("does not match media types that merely contain 'image' but do not start with 'image/'", () => {
		expect(
			isImageAttachment(
				attachment({ kind: "file", mediaType: "application/x-image" }),
			),
		).toBe(false);
	});
});
