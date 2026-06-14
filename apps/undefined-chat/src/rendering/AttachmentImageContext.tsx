import {
	type ReactNode,
	createContext,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useRef,
} from "react";
import type { RuntimeClient } from "../runtime-client/types";

export type LoadedAttachmentBlob = {
	url: string;
	mediaType: string;
};

type AttachmentImageContextValue = {
	loadAttachmentBlob: (uid: string) => Promise<LoadedAttachmentBlob | null>;
};

const AttachmentImageContext =
	createContext<AttachmentImageContextValue | null>(null);

const DEFAULT_MAX_CACHE_SIZE = 60;

export type AttachmentImageProviderProps = {
	/** 仅依赖 previewAttachment，便于测试以最小桩注入 */
	client: Pick<RuntimeClient, "previewAttachment">;
	/** blob 缓存上限，超出按 LRU 淘汰并 revoke。默认 60。 */
	maxCacheSize?: number;
	children: ReactNode;
};

/**
 * 通过 Tauri 命令（带 auth）按 UID 拉取附件字节并转为 blob URL 供 `<img>` 渲染。
 *
 * Runtime API 要求 `X-Undefined-API-Key` header，浏览器 `<img src=远程url>` 不带该
 * header 会被拦截（401）；故图片统一经 `client.previewAttachment`（Rust 端带 auth）
 * 拉字节，在前端转 blob URL 渲染。
 *
 * - LRU 缓存 uid→blobUrl：缩略图/正文图/全屏大图复用同一 blob，避免重复拉取。
 * - inflight 去重：同一 UID 并发请求只发一次。
 * - blob URL 归本 Provider 所有：消费组件**不**自行 revoke（缩略图与大图共享同一
 *   URL，组件卸载即 revoke 会让仍打开的大图破图），仅在 LRU 淘汰或 Provider 卸载
 *   时 revoke。
 */
export function AttachmentImageProvider({
	client,
	maxCacheSize = DEFAULT_MAX_CACHE_SIZE,
	children,
}: AttachmentImageProviderProps) {
	const cacheRef = useRef<Map<string, LoadedAttachmentBlob>>(new Map());
	const inflightRef = useRef<Map<string, Promise<LoadedAttachmentBlob | null>>>(
		new Map(),
	);

	const loadAttachmentBlob = useCallback(
		(uid: string): Promise<LoadedAttachmentBlob | null> => {
			const cache = cacheRef.current;
			const inflight = inflightRef.current;

			const cached = cache.get(uid);
			if (cached) {
				// LRU touch：移到队尾
				cache.delete(uid);
				cache.set(uid, cached);
				return Promise.resolve(cached);
			}

			const pending = inflight.get(uid);
			if (pending) return pending;

			const promise = (async (): Promise<LoadedAttachmentBlob | null> => {
				try {
					const result = await client.previewAttachment({ attachmentId: uid });
					if (!result.ok || result.bytes.length === 0) {
						return null;
					}
					const mediaType = result.mediaType || "application/octet-stream";
					const blob = new Blob([new Uint8Array(result.bytes)], {
						type: mediaType,
					});
					const loaded: LoadedAttachmentBlob = {
						url: URL.createObjectURL(blob),
						mediaType,
					};
					cache.set(uid, loaded);
					// 超上限淘汰最旧（队首）并 revoke
					while (cache.size > maxCacheSize) {
						const oldestKey = cache.keys().next().value;
						if (oldestKey === undefined) break;
						const victim = cache.get(oldestKey);
						cache.delete(oldestKey);
						if (victim) URL.revokeObjectURL(victim.url);
					}
					return loaded;
				} catch {
					return null;
				} finally {
					inflight.delete(uid);
				}
			})();

			inflight.set(uid, promise);
			return promise;
		},
		[client, maxCacheSize],
	);

	// Provider 卸载时释放全部 blob URL
	useEffect(() => {
		const cache = cacheRef.current;
		return () => {
			for (const { url } of cache.values()) {
				URL.revokeObjectURL(url);
			}
			cache.clear();
		};
	}, []);

	const value = useMemo<AttachmentImageContextValue>(
		() => ({ loadAttachmentBlob }),
		[loadAttachmentBlob],
	);

	return (
		<AttachmentImageContext.Provider value={value}>
			{children}
		</AttachmentImageContext.Provider>
	);
}

/**
 * 获取附件图片加载能力。必须在 {@link AttachmentImageProvider} 内使用。
 */
export function useAttachmentImage(): AttachmentImageContextValue {
	const value = useContext(AttachmentImageContext);
	if (value === null) {
		throw new Error(
			"useAttachmentImage must be used within an AttachmentImageProvider",
		);
	}
	return value;
}
