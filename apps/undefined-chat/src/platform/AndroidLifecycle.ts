import { getCurrentWindow } from "@tauri-apps/api/window";
import type { ChatStore } from "../chat-store/store";

/**
 * Android 生命周期管理
 * - 监听应用暂停/恢复事件
 * - 恢复时重新连接并补齐事件
 */
export function setupAndroidLifecycle(store: ChatStore): () => void {
	const unlisteners: Array<() => void> = [];
	const appWindow = getCurrentWindow();

	// 监听应用暂停事件
	appWindow
		.listen<string>("android-pause", () => {
			console.log("[Lifecycle] App paused");
			// 可以在这里保存状态或清理资源
		})
		.then((unlisten: () => void) => {
			unlisteners.push(unlisten);
		})
		.catch((err: unknown) => {
			console.error("[Lifecycle] Failed to listen android-pause:", err);
		});

	// 监听应用恢复事件
	appWindow
		.listen<string>("android-resume", async () => {
			console.log("[Lifecycle] App resumed, re-bootstrapping...");

			try {
				// 重新初始化连接
				await store.bootstrap();

				// 获取当前活跃任务
				const state = store.getSnapshot();
				const activeJobs = Object.values(state.activeJobsByConversation);

				console.log(
					`[Lifecycle] Reconnected, ${activeJobs.length} active jobs found`,
				);

				// 每个活跃任务可能在暂停期间产生了新事件
				// bootstrap 会自动重新订阅事件流，补齐遗漏的事件
				if (activeJobs.length > 0) {
					console.log(
						"[Lifecycle] Event streams will be resumed automatically",
					);
				}
			} catch (err) {
				console.error("[Lifecycle] Failed to reconnect:", err);
			}
		})
		.then((unlisten: () => void) => {
			unlisteners.push(unlisten);
		})
		.catch((err: unknown) => {
			console.error("[Lifecycle] Failed to listen android-resume:", err);
		});

	// 返回清理函数
	return () => {
		for (const unlisten of unlisteners) {
			unlisten();
		}
	};
}

/**
 * 检测是否在 Android 平台
 */
export function isAndroid(): boolean {
	if (typeof window === "undefined") {
		return false;
	}
	// Tauri Android 会在 navigator.userAgent 中包含 "Android"
	return /Android/i.test(navigator.userAgent);
}
