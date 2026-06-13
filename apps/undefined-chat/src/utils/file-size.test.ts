import { describe, expect, it } from "vitest";
import { formatFileSize } from "./file-size";

describe("formatFileSize", () => {
	it("formats zero bytes", () => {
		expect(formatFileSize(0)).toBe("0 B");
	});

	it("formats negative bytes as 0 B", () => {
		expect(formatFileSize(-100)).toBe("0 B");
	});

	it("formats bytes less than 1KB", () => {
		expect(formatFileSize(1)).toBe("1 B");
		expect(formatFileSize(100)).toBe("100 B");
		expect(formatFileSize(1023)).toBe("1023 B");
	});

	it("formats kilobytes", () => {
		expect(formatFileSize(1024)).toBe("1 KB");
		expect(formatFileSize(1536)).toBe("1.5 KB");
		expect(formatFileSize(10240)).toBe("10 KB");
		expect(formatFileSize(1024 * 999)).toBe("999 KB");
	});

	it("formats megabytes", () => {
		expect(formatFileSize(1024 * 1024)).toBe("1 MB");
		expect(formatFileSize(1024 * 1024 * 1.5)).toBe("1.5 MB");
		expect(formatFileSize(1024 * 1024 * 10)).toBe("10 MB");
		expect(formatFileSize(1024 * 1024 * 999)).toBe("999 MB");
	});

	it("formats gigabytes", () => {
		expect(formatFileSize(1024 * 1024 * 1024)).toBe("1 GB");
		expect(formatFileSize(1024 * 1024 * 1024 * 2.5)).toBe("2.5 GB");
		expect(formatFileSize(1024 * 1024 * 1024 * 10)).toBe("10 GB");
	});

	it("rounds to one decimal place", () => {
		expect(formatFileSize(1536)).toBe("1.5 KB");
		expect(formatFileSize(1638)).toBe("1.6 KB"); // 1638 / 1024 = 1.6
		expect(formatFileSize(1024 * 1024 * 1.55)).toBe("1.6 MB");
	});
});
