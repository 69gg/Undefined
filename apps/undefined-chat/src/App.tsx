import { open } from "@tauri-apps/plugin-dialog";
import {
	type FormEvent,
	useEffect,
	useMemo,
	useState,
	useSyncExternalStore,
} from "react";
import { createChatStore, isJobRunning } from "./chat-store/store";
import { ConversationList } from "./conversation-list/ConversationList";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { ImageViewerModal } from "./image-viewer/ImageViewerModal";
import { useImageViewer } from "./image-viewer/useImageViewer";
import { MessageComposer } from "./message-composer/MessageComposer";
import { MessageTimeline } from "./message-timeline/MessageTimeline";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import type { Attachment } from "./runtime-client/types";
import { useTheme } from "./theme/use-theme";

export function App() {
	const { effectiveTheme } = useTheme();
	const client = useMemo(() => createTauriRuntimeClient(), []);
	const store = useMemo(() => createChatStore({ client }), [client]);
	const { openImage, closeImage } = useImageViewer(store);
	const state = useSyncExternalStore(
		store.subscribe,
		store.getSnapshot,
		store.getSnapshot,
	);

	// 布局状态
	const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
	const [isMobileSidebarActive, setIsMobileSidebarActive] = useState(false);
	const [isSettingsOpen, setIsSettingsOpen] = useState(false);
	const isMobile = useMediaQuery("(max-width: 768px)");

	const selectedConversationId =
		state.selectedConversationId ?? state.conversations[0]?.id ?? null;
	const selectedHistory = selectedConversationId
		? (state.historyByConversation[selectedConversationId]?.items ?? [])
		: [];
	const activeJob = selectedConversationId
		? (state.activeJobsByConversation[selectedConversationId] ?? null)
		: null;
	const activeEvents = activeJob
		? (state.eventsByJob[activeJob.jobId] ?? [])
		: [];

	const [setupRuntimeUrl, setSetupRuntimeUrl] = useState(
		state.runtimeConfig?.runtimeUrl ?? "http://127.0.0.1:8788",
	);
	const [setupApiKey, setSetupApiKey] = useState("");
	const [allowInsecureStorageFallback, setAllowInsecureStorageFallback] =
		useState(false);
	const [setupError, setSetupError] = useState<string | null>(null);

	const needsSetup =
		Boolean(state.error?.includes("请先配置")) ||
		!state.runtimeConfig?.runtimeUrl ||
		!state.runtimeConfig.hasApiKey;

	useEffect(() => {
		void store.bootstrap();
	}, [store]);

	// 应用主题到 DOM
	useEffect(() => {
		document.documentElement.dataset.theme = effectiveTheme;
	}, [effectiveTheme]);

	// 当需要配置时，同步当前 URL
	useEffect(() => {
		if (state.runtimeConfig?.runtimeUrl) {
			setSetupRuntimeUrl(state.runtimeConfig.runtimeUrl);
		}
	}, [state.runtimeConfig?.runtimeUrl]);

	async function handleSetupSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setSetupError(null);
		try {
			await client.saveRuntimeConfig(setupRuntimeUrl);
			if (allowInsecureStorageFallback) {
				await client.confirmInsecureStorageFallback();
			}
			await client.saveApiKey(setupApiKey);
			setSetupApiKey("");
			setIsSettingsOpen(false);
			await store.bootstrap();
		} catch (err) {
			setSetupError(err instanceof Error ? err.message : String(err));
		}
	}

	async function saveAttachment(attachment: Attachment): Promise<void> {
		try {
			const result = await client.saveAttachment({
				attachmentId: attachment.id,
				fileName: attachment.name,
			});
			if (!result.ok) {
				window.alert(result.body ?? "附件保存失败");
				return;
			}
			window.alert(`已保存 ${result.savedFileName ?? attachment.name}`);
		} catch (err) {
			window.alert(err instanceof Error ? err.message : String(err));
		}
	}

	async function previewAttachment(attachment: Attachment): Promise<void> {
		try {
			const result = await client.previewAttachment({
				attachmentId: attachment.id,
			});
			if (!result.ok || result.bytes.length === 0) {
				window.alert(result.body ?? "附件无法预览");
				return;
			}
			const blob = new Blob([new Uint8Array(result.bytes)], {
				type: result.mediaType ?? attachment.mediaType,
			});
			const url = URL.createObjectURL(blob);
			window.open(url, "_blank", "noopener,noreferrer");
		} catch (err) {
			window.alert(err instanceof Error ? err.message : String(err));
		}
	}

	async function addAttachment(conversationId: string): Promise<void> {
		try {
			const selected = await open({
				multiple: false,
				directory: false,
				title: "选择附件",
				pickerMode: "document",
				fileAccessMode: "copy",
			});
			if (typeof selected === "string") {
				await store.addAttachmentPath(conversationId, selected);
			}
		} catch (err) {
			window.alert(err instanceof Error ? err.message : String(err));
		}
	}

	function handleShortcutClick(prompt: string) {
		if (selectedConversationId) {
			store.updateDraft(selectedConversationId, prompt);
		}
	}

	const showModal = needsSetup || isSettingsOpen;

	return (
		<main className="chat-app">
			{/* 移动端侧边栏背景遮罩 */}
			<div
				className={`sidebar-overlay ${isMobileSidebarActive ? "active" : ""}`}
				onClick={() => setIsMobileSidebarActive(false)}
				onKeyDown={(e) => {
					if (e.key === "Escape") setIsMobileSidebarActive(false);
				}}
				role="presentation"
			/>

			{/* 侧边栏 */}
			<ConversationList
				conversations={state.conversations}
				isCollapsed={isSidebarCollapsed}
				onCreate={() => {
					void store.createConversation();
				}}
				onOpenSettings={() => setIsSettingsOpen(true)}
				onSelect={(conversationId) => {
					void store.selectConversation(conversationId);
					setIsMobileSidebarActive(false);
				}}
				onToggleCollapse={() => setIsSidebarCollapsed(true)}
				selectedConversationId={selectedConversationId}
			/>

			{/* 主工作区 */}
			<section className="chat-workspace" aria-label="聊天">
				{/* 顶栏 */}
				<header className="chat-topbar">
					<div className="topbar-left">
						{/* 侧边栏折叠时的展示按钮，或移动端的菜单按钮 */}
						{isSidebarCollapsed || isMobile ? (
							<button
								className="icon-button"
								onClick={() => {
									if (isMobile) {
										setIsMobileSidebarActive(true);
									} else {
										setIsSidebarCollapsed(false);
									}
								}}
								title="展开菜单"
								type="button"
							>
								<svg
									fill="none"
									height="16"
									stroke="currentColor"
									strokeLinecap="round"
									strokeLinejoin="round"
									strokeWidth="2"
									viewBox="0 0 24 24"
									width="16"
								>
									<title>展开菜单</title>
									<line x1="3" x2="21" y1="12" y2="12" />
									<line x1="3" x2="21" y1="6" y2="6" />
									<line x1="3" x2="21" y1="18" y2="18" />
								</svg>
							</button>
						) : null}

						<div className="chat-title-block">
							<strong>
								{state.conversations.find(
									(item) => item.id === selectedConversationId,
								)?.title ?? "默认会话"}
							</strong>
							<div style={{ display: "flex", gap: "6px", marginTop: "2px" }}>
								<span className={`connection-pill ${state.connectionState}`}>
									{connectionStateLabel(state.connectionState)}
								</span>
							</div>
						</div>
					</div>

					<div className="runtime-indicator">
						<span>{state.runtimeConfig?.runtimeUrl ?? "Runtime"}</span>
					</div>
				</header>

				{/* 模态框 / 配置面板 */}
				{showModal ? (
					<div className="setup-panel-container">
						<form className="setup-panel" onSubmit={handleSetupSubmit}>
							<div
								style={{
									display: "flex",
									justifyContent: "space-between",
									alignItems: "center",
								}}
							>
								<h3>{needsSetup ? "连接到 Runtime" : "Runtime 配置"}</h3>
								{!needsSetup ? (
									<button
										className="icon-button"
										onClick={() => setIsSettingsOpen(false)}
										style={{
											border: "none",
											boxShadow: "none",
											fontSize: "1.2rem",
										}}
										title="关闭"
										type="button"
									>
										×
									</button>
								) : null}
							</div>
							<label>
								<span>Runtime URL</span>
								<input
									autoComplete="url"
									onChange={(event) =>
										setSetupRuntimeUrl(event.currentTarget.value)
									}
									required
									type="url"
									value={setupRuntimeUrl}
								/>
							</label>
							<label>
								<span>API Key</span>
								<input
									autoComplete="current-password"
									onChange={(event) =>
										setSetupApiKey(event.currentTarget.value)
									}
									placeholder={needsSetup ? "请输入 API Key" : "••••••••"}
									required={needsSetup}
									type="password"
									value={setupApiKey}
								/>
							</label>
							<label className="setup-checkbox">
								<input
									checked={allowInsecureStorageFallback}
									onChange={(event) =>
										setAllowInsecureStorageFallback(event.currentTarget.checked)
									}
									type="checkbox"
								/>
								<span>允许不安全存储降级</span>
							</label>
							<button type="submit">保存并连接</button>
							<p>
								密钥优先保存在系统凭据管理器；勾选后仅在不可用时写入本地明文降级。
							</p>
							{setupError ? (
								<strong style={{ color: "var(--status-error-text)" }}>
									{setupError}
								</strong>
							) : null}
						</form>
					</div>
				) : state.error ? (
					<p className="app-error">{state.error}</p>
				) : null}

				{/* 消息时间线 */}
				<MessageTimeline
					activeJob={activeJob}
					connectionState={state.connectionState}
					events={activeEvents}
					items={selectedHistory}
					onPreviewAttachment={(attachment) => {
						void previewAttachment(attachment);
					}}
					onPreviewHtml={(input) => {
						void client.openHtmlPreview(input);
					}}
					onSaveAttachment={(attachment) => {
						void saveAttachment(attachment);
					}}
					onShortcutClick={handleShortcutClick}
					onAddReference={(messageId, quote) => {
						if (selectedConversationId) {
							store.addReference(selectedConversationId, {
								messageId,
								quote,
							});
						}
					}}
					onOpenImage={openImage}
					runtimeUrl={state.runtimeConfig?.runtimeUrl}
				/>

				{/* 输入框 */}
				<MessageComposer
					attachmentQueue={
						selectedConversationId
							? (state.attachmentsByConversation[selectedConversationId] ?? [])
							: []
					}
					commandSuggestions={state.commands}
					disabled={isJobRunning(activeJob)}
					draft={
						selectedConversationId
							? (state.draftsByConversation[selectedConversationId] ?? "")
							: ""
					}
					references={
						selectedConversationId
							? (state.referencesByConversation[selectedConversationId] ?? [])
							: []
					}
					onAddAttachment={() => {
						if (!selectedConversationId) {
							return;
						}
						void addAttachment(selectedConversationId);
					}}
					onClearAttachment={(attachmentId) => {
						if (selectedConversationId) {
							store.clearAttachment(selectedConversationId, attachmentId);
						}
					}}
					onClearReference={(messageId) => {
						if (selectedConversationId) {
							store.clearReference(selectedConversationId, messageId);
						}
					}}
					onDraftChange={(draft) => {
						if (selectedConversationId) {
							store.updateDraft(selectedConversationId, draft);
						}
					}}
					onSend={() => {
						void store.sendSelectedMessage();
					}}
				/>
				{state.sendError ? (
					<p className="app-error">{state.sendError}</p>
				) : null}
			</section>

			<ImageViewerModal imageViewer={state.imageViewer} onClose={closeImage} />
		</main>
	);
}

function connectionStateLabel(state: string): string {
	const labels: Record<string, string> = {
		idle: "待连接",
		connecting: "正在连接",
		connected: "已连接",
		streaming: "事件流",
		resuming: "正在续接",
		json_fallback: "JSON 轮询",
		disconnected: "连接断开",
	};
	return labels[state] ?? state;
}
