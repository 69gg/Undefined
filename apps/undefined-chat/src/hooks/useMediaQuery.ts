import { useCallback, useSyncExternalStore } from "react";

/**
 * 订阅一个 CSS media query，返回其当前是否匹配。
 * 基于 matchMedia + useSyncExternalStore，会随窗口缩放/旋屏实时更新，
 * 替代在渲染期直接读取 window.innerWidth（不响应 resize）的写法。
 */
export function useMediaQuery(query: string): boolean {
	const subscribe = useCallback(
		(callback: () => void): (() => void) => {
			if (typeof window === "undefined" || !window.matchMedia) {
				return () => {};
			}
			const mql = window.matchMedia(query);
			mql.addEventListener("change", callback);
			return () => mql.removeEventListener("change", callback);
		},
		[query],
	);

	const getSnapshot = useCallback((): boolean => {
		if (typeof window === "undefined" || !window.matchMedia) {
			return false;
		}
		return window.matchMedia(query).matches;
	}, [query]);

	return useSyncExternalStore(subscribe, getSnapshot, () => false);
}
