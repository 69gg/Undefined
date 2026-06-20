import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type {
	AttachmentPreviewResult,
	RuntimeClient,
} from "../runtime-client/types";
import {
	AttachmentImageProvider,
	useAttachmentImage,
} from "./AttachmentImageContext";

type PreviewClient = Pick<RuntimeClient, "previewAttachment">;

function imageResult(): AttachmentPreviewResult {
	return {
		status: 200,
		ok: true,
		mediaType: "image/png",
		bytes: [137, 80, 78, 71],
		body: null,
	};
}

function makeClient(impl?: () => Promise<AttachmentPreviewResult>) {
	const previewAttachment = vi.fn(impl ?? (async () => imageResult()));
	const client: PreviewClient = { previewAttachment };
	return { client, previewAttachment };
}

function makeWrapper(client: PreviewClient, maxCacheSize?: number) {
	return function Wrapper({ children }: { children: ReactNode }) {
		return (
			<AttachmentImageProvider client={client} maxCacheSize={maxCacheSize}>
				{children}
			</AttachmentImageProvider>
		);
	};
}

describe("AttachmentImageContext", () => {
	it("缓存命中：同一 UID 只拉取一次，返回同一 blob URL", async () => {
		const { client, previewAttachment } = makeClient();
		const { result } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client),
		});

		const a = await result.current.loadAttachmentBlob("pic_1");
		const b = await result.current.loadAttachmentBlob("pic_1");

		expect(a?.url).toBeTruthy();
		expect(a?.url).toBe(b?.url);
		expect(previewAttachment).toHaveBeenCalledTimes(1);
	});

	it("并发去重：同时请求同一 UID 只发一次", async () => {
		const { client, previewAttachment } = makeClient();
		const { result } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client),
		});

		const [a, b] = await Promise.all([
			result.current.loadAttachmentBlob("pic_1"),
			result.current.loadAttachmentBlob("pic_1"),
		]);

		expect(a?.url).toBe(b?.url);
		expect(previewAttachment).toHaveBeenCalledTimes(1);
	});

	it("ok:false 返回 null", async () => {
		const { client } = makeClient(async () => ({
			status: 415,
			ok: false,
			mediaType: null,
			bytes: [],
			body: "nope",
		}));
		const { result } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client),
		});

		expect(await result.current.loadAttachmentBlob("pic_1")).toBeNull();
	});

	it("previewAttachment 抛错返回 null", async () => {
		const { client } = makeClient(async () => {
			throw new Error("boom");
		});
		const { result } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client),
		});

		expect(await result.current.loadAttachmentBlob("pic_1")).toBeNull();
	});

	it("LRU 超上限淘汰最旧并 revoke", async () => {
		const revokeSpy = vi.spyOn(URL, "revokeObjectURL");
		const { client, previewAttachment } = makeClient();
		const { result } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client, 2),
		});

		await result.current.loadAttachmentBlob("pic_1");
		await result.current.loadAttachmentBlob("pic_2");
		await result.current.loadAttachmentBlob("pic_3"); // 淘汰最旧 pic_1

		expect(revokeSpy).toHaveBeenCalledTimes(1);

		// pic_1 已被淘汰，再请求会重新拉取（总计 4 次）
		await result.current.loadAttachmentBlob("pic_1");
		expect(previewAttachment).toHaveBeenCalledTimes(4);

		revokeSpy.mockRestore();
	});

	it("Provider 卸载时 revoke 全部 blob URL", async () => {
		const revokeSpy = vi.spyOn(URL, "revokeObjectURL");
		const { client } = makeClient();
		const { result, unmount } = renderHook(() => useAttachmentImage(), {
			wrapper: makeWrapper(client),
		});

		await result.current.loadAttachmentBlob("pic_1");
		await result.current.loadAttachmentBlob("pic_2");
		revokeSpy.mockClear();

		unmount();

		expect(revokeSpy).toHaveBeenCalledTimes(2);
		revokeSpy.mockRestore();
	});
});
