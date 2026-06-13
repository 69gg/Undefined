import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Mock Tauri API
vi.mock("@tauri-apps/api/core", () => ({
	invoke: vi.fn().mockResolvedValue({
		os: "linux",
		arch: "x86_64",
		version: "test",
	}),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));
