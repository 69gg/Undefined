import { TauriEvent } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { ChatStore } from "../chat-store/store";

/**
 * Android 生命周期管理
 * - 监听应用暂停/恢复事件
 * - 恢复时重新 bootstrap 并恢复 Runtime 事件订阅
 */
export function setupAndroidLifecycle(store: ChatStore): () => void {
	const unlisteners: Array<() => void> = [];
	const appWindow = getCurrentWindow();

	// 监听应用暂停事件
	appWindow
		.listen<string>(TauriEvent.WINDOW_SUSPENDED, () => {
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
		.listen<string>(TauriEvent.WINDOW_RESUMED, async () => {
			console.log("[Lifecycle] App resumed, re-bootstrapping...");

			try {
				// 重新初始化连接：保留当前选中会话，避免切后台返回后丢失正在查看的会话；
				// 标记为续接（resuming）以反映真实连接状态
				const previousSelection =
					store.getSnapshot().selectedConversationId ?? undefined;
				await store.bootstrap({
					preserveSelectionId: previousSelection,
					resuming: true,
				});

				// 获取当前活跃任务
				const state = store.getSnapshot();
				const activeJobs = Object.values(state.activeJobsByConversation);

				console.log(
					`[Lifecycle] Reconnected, ${activeJobs.length} active jobs found`,
				);

				// bootstrap 会重新订阅事件流；断线期间的事件补齐仍由
				// store 内部的 SSE error/closed fallback 处理。
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
