import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatStore } from "../chat-store/store";
import { useImageViewer } from "./useImageViewer";

describe("useImageViewer", () => {
	it("openImage 应该调用 store.dispatch 并打开图片查看器", () => {
		const mockDispatch = vi.fn();
		const mockStore = {
			dispatch: mockDispatch,
		} as unknown as ChatStore;

		const { result } = renderHook(() => useImageViewer(mockStore));

		result.current.openImage("https://example.com/image.jpg", "测试图片");

		expect(mockDispatch).toHaveBeenCalledWith({
			type: "imageViewer/open",
			src: "https://example.com/image.jpg",
			alt: "测试图片",
		});
	});

	it("closeImage 应该调用 store.dispatch 并关闭图片查看器", () => {
		const mockDispatch = vi.fn();
		const mockStore = {
			dispatch: mockDispatch,
		} as unknown as ChatStore;

		const { result } = renderHook(() => useImageViewer(mockStore));

		result.current.closeImage();

		expect(mockDispatch).toHaveBeenCalledWith({
			type: "imageViewer/close",
		});
	});

	it("返回的函数应该保持稳定（使用 useCallback）", () => {
		const mockDispatch = vi.fn();
		const mockStore = {
			dispatch: mockDispatch,
		} as unknown as ChatStore;

		const { result, rerender } = renderHook(() => useImageViewer(mockStore));

		const firstOpenImage = result.current.openImage;
		const firstCloseImage = result.current.closeImage;

		rerender();

		expect(result.current.openImage).toBe(firstOpenImage);
		expect(result.current.closeImage).toBe(firstCloseImage);
	});
});
