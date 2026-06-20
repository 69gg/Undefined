import { describe, expect, it } from "vitest";
import { getFileIcon } from "./file-icon";

describe("getFileIcon", () => {
	it.each([
		["image/png", "IMG"],
		["video/mp4", "VID"],
		["audio/mp3", "AUD"],
		["text/plain", "TXT"],
		["application/pdf", "PDF"],
		["application/zip", "ZIP"],
		["application/x-tar", "ZIP"],
		["application/json", "DAT"],
		["application/xml", "DAT"],
		["application/yaml", "DAT"],
		["application/octet-stream", "FILE"],
		["", "FILE"],
	])("%s → %s", (mediaType, expected) => {
		expect(getFileIcon(mediaType)).toBe(expected);
	});
});
