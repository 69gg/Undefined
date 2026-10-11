import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useLayoutEffect,
	useMemo,
} from "react";
import type { RuntimeClient } from "../runtime-client/types";

export type LoadedAttachmentBlob = {
	url: string;
	mediaType: string;
};

type AttachmentImageContextValue = {
	loadAttachmentBlob: (uid: string) => Promise<LoadedAttachmentBlob | null>;
	retainAttachmentBlob: (uid: string) => () => void;
	retainBlobUrl: (url: string) => (() => void) | undefined;
};

const AttachmentImageContext =
	createContext<AttachmentImageContextValue | null>(null);

const DEFAULT_MAX_CACHE_SIZE = 60;

export type AttachmentImageProviderProps = {
	/** 仅依赖 previewAttachment，便于测试以最小桩注入 */
	client: Pick<RuntimeClient, "previewAttachment">;
	/** 按 Runtime URL 隔离 UID 缓存，保持消费组件与 DOM 的生命周期。 */
	runtimeUrl?: string | null;
	/** blob 缓存目标上限；超出时仅淘汰无消费者的 LRU 项。默认 60。 */
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
 *   URL，组件卸载即 revoke 会让仍打开的大图破图）。消费者持有引用期间跳过
 *   LRU 淘汰；切换 Runtime 或 Provider 卸载时统一 revoke。
 */
export function AttachmentImageProvider({
	client,
	runtimeUrl,
	maxCacheSize = DEFAULT_MAX_CACHE_SIZE,
	children,
}: AttachmentImageProviderProps) {
	const scope = useMemo(
		() => ({
			runtimeUrl,
			cache: new Map<string, LoadedAttachmentBlob>(),
			inflight: new Map<string, Promise<LoadedAttachmentBlob | null>>(),
			consumers: new Map<string, number>(),
			generation: 0,
		}),
		[runtimeUrl],
	);

	const evictUnused = useCallback(() => {
		for (const [uid, loaded] of scope.cache) {
			if (scope.cache.size <= maxCacheSize) break;
			if (scope.consumers.has(uid)) continue;
			scope.cache.delete(uid);
			URL.revokeObjectURL(loaded.url);
		}
	}, [maxCacheSize, scope]);

	const retainAttachmentBlob = useCallback(
		(uid: string): (() => void) => {
			const generation = scope.generation;
			scope.consumers.set(uid, (scope.consumers.get(uid) ?? 0) + 1);
			let released = false;
			return () => {
				if (released || generation !== scope.generation) return;
				released = true;
				const remaining = (scope.consumers.get(uid) ?? 1) - 1;
				if (remaining > 0) scope.consumers.set(uid, remaining);
				else scope.consumers.delete(uid);
				evictUnused();
			};
		},
		[scope, evictUnused],
	);

	const retainBlobUrl = useCallback(
		(url: string): (() => void) | undefined => {
			for (const [uid, loaded] of scope.cache) {
				if (loaded.url === url) return retainAttachmentBlob(uid);
			}
			return undefined;
		},
		[scope, retainAttachmentBlob],
	);

	const loadAttachmentBlob = useCallback(
		(uid: string): Promise<LoadedAttachmentBlob | null> => {
			const { cache, inflight } = scope;

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
				const generation = scope.generation;
				try {
					const result = await client.previewAttachment({ attachmentId: uid });
					if (generation !== scope.generation) return null;
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
					evictUnused();
					return loaded;
				} catch {
					return null;
				} finally {
					if (generation === scope.generation) inflight.delete(uid);
				}
			})();

			inflight.set(uid, promise);
			return promise;
		},
		[client, evictUnused, scope],
	);

	// 切换 Runtime 或卸载时释放全部 blob URL，拒绝旧作用域迟到的响应。
	useEffect(() => {
		const { cache, inflight } = scope;
		return () => {
			scope.generation += 1;
			inflight.clear();
			scope.consumers.clear();
			for (const { url } of cache.values()) {
				URL.revokeObjectURL(url);
			}
			cache.clear();
		};
	}, [scope]);

	const value = useMemo<AttachmentImageContextValue>(
		() => ({ loadAttachmentBlob, retainAttachmentBlob, retainBlobUrl }),
		[loadAttachmentBlob, retainAttachmentBlob, retainBlobUrl],
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

/** 大图独立持有 Provider 的 URL；外部图片和无 Provider 的查看器无需持有。 */
export function useRetainedAttachmentBlobUrl(url: string | null): void {
	const value = useContext(AttachmentImageContext);
	// 在被动 effect 释放缩略图前接管引用，支持同次渲染中移除源缩略图。
	useLayoutEffect(() => {
		if (url) return value?.retainBlobUrl(url);
	}, [value, url]);
}
