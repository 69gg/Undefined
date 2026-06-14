import { open } from "@tauri-apps/plugin-dialog";
import {
	type FormEvent,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
	useSyncExternalStore,
} from "react";
import { createChatStore, isJobRunning } from "./chat-store/store";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { ConversationList } from "./conversation-list/ConversationList";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { ImageViewerModal } from "./image-viewer/ImageViewerModal";
import { useImageViewer } from "./image-viewer/useImageViewer";
import { MessageComposer } from "./message-composer/MessageComposer";
import { MessageTimeline } from "./message-timeline/MessageTimeline";
import { isAndroid, setupAndroidLifecycle } from "./platform/AndroidLifecycle";
import { KeybindingManager } from "./platform/KeybindingManager";
import { AttachmentImageProvider } from "./rendering/AttachmentImageContext";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import type { Attachment } from "./runtime-client/types";
import { useTheme } from "./theme/use-theme";
import { isImageAttachment } from "./utils/attachment";

const CONVERSATION_SIDEBAR_ID = "conversation-sidebar";

export function App() {
	const { effectiveTheme } = useTheme();
	const client = useMemo(() => createTauriRuntimeClient(), []);
	const store = useMemo(() => createChatStore({ client }), [client]);
	const keybindingManager = useMemo(() => new KeybindingManager(), []);
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
	const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
	const [composerFocusRequest, setComposerFocusRequest] = useState<{
		id: number;
		commandMode: boolean;
	} | null>(null);
	const mobileMenuButtonRef = useRef<HTMLButtonElement | null>(null);
	const previousMobileFocusRef = useRef<HTMLElement | null>(null);
	const previewImageUrlRef = useRef<string | null>(null);
	const isMobile = useMediaQuery("(max-width: 768px)");

	const pendingDeleteConversation = pendingDeleteId
		? (state.conversations.find((item) => item.id === pendingDeleteId) ?? null)
		: null;

	const selectedConversationId =
		state.selectedConversationId || state.conversations[0]?.id || null;
	const selectedHistoryState = selectedConversationId
		? state.historyByConversation[selectedConversationId]
		: undefined;
	const selectedHistory = selectedHistoryState?.items ?? [];
	// 历史尚未加载或加载中（区分"加载中"与"空会话/欢迎页"）
	const historyLoading =
		selectedConversationId !== null &&
		(selectedHistoryState === undefined || selectedHistoryState.loading);
	const historyError = selectedHistoryState?.error ?? null;
	const activeJob = selectedConversationId
		? (state.activeJobsByConversation[selectedConversationId] ?? null)
		: null;

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

	useEffect(() => {
		if (!isAndroid()) {
			return undefined;
		}
		return setupAndroidLifecycle(store);
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
			if (isImageAttachment(attachment)) {
				if (previewImageUrlRef.current) {
					URL.revokeObjectURL(previewImageUrlRef.current);
				}
				previewImageUrlRef.current = url;
				openImage(url, attachment.name);
				return;
			}
			window.open(url, "_blank", "noopener,noreferrer");
			window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
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
			return;
		}
		// 尚无会话：先自动创建再把示例填入草稿
		void store.createConversation().then(() => {
			const conversationId = store.getSnapshot().selectedConversationId;
			if (conversationId) {
				store.updateDraft(conversationId, prompt);
			}
		});
	}

	const showModal = needsSetup || isSettingsOpen;

	const closeMobileSidebar = useCallback((): void => {
		setIsMobileSidebarActive(false);
	}, []);

	function openMobileSidebar(): void {
		previousMobileFocusRef.current =
			document.activeElement as HTMLElement | null;
		setIsMobileSidebarActive(true);
	}

	const requestComposerFocus = useCallback((commandMode: boolean): void => {
		setComposerFocusRequest((request) => ({
			id: (request?.id ?? 0) + 1,
			commandMode,
		}));
	}, []);

	function jumpToLoadedMessage(messageId: string): boolean {
		const target = Array.from(
			document.querySelectorAll<HTMLElement>("[data-message-id]"),
		).find((element) => element.dataset.messageId === messageId);
		if (!target) {
			return false;
		}
		target.scrollIntoView({ block: "center", behavior: "smooth" });
		target.classList.add("message-jump-highlight");
		window.setTimeout(() => {
			target.classList.remove("message-jump-highlight");
		}, 1600);
		return true;
	}

	function handleJumpReference(messageId: string): void {
		if (jumpToLoadedMessage(messageId)) {
			return;
		}
		if (selectedConversationId && selectedHistoryState?.hasMore) {
			void store.loadMoreHistory(selectedConversationId).then(() => {
				requestAnimationFrame(() => {
					if (!jumpToLoadedMessage(messageId)) {
						window.alert("引用消息暂未加载，请继续加载更早消息后重试");
					}
				});
			});
			return;
		}
		window.alert("引用消息不在当前会话历史中");
	}

	const closeImageViewer = useCallback((): void => {
		closeImage();
		if (previewImageUrlRef.current) {
			URL.revokeObjectURL(previewImageUrlRef.current);
			previewImageUrlRef.current = null;
		}
	}, [closeImage]);

	useEffect(() => {
		return () => {
			if (previewImageUrlRef.current) {
				URL.revokeObjectURL(previewImageUrlRef.current);
				previewImageUrlRef.current = null;
			}
		};
	}, []);

	useEffect(() => {
		if (!isMobile || !isMobileSidebarActive) {
			return;
		}
		requestAnimationFrame(() => {
			const sidebar = document.getElementById(CONVERSATION_SIDEBAR_ID);
			const firstControl = sidebar?.querySelector<HTMLElement>(
				"button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])",
			);
			firstControl?.focus();
		});
	}, [isMobile, isMobileSidebarActive]);

	useEffect(() => {
		if (isMobileSidebarActive) {
			return;
		}
		const previous = previousMobileFocusRef.current;
		if (previous && document.contains(previous)) {
			previous.focus();
		}
		previousMobileFocusRef.current = null;
	}, [isMobileSidebarActive]);

	useEffect(() => {
		const visualViewport = window.visualViewport;
		const updateKeyboardInset = () => {
			const inset = visualViewport
				? Math.max(
						0,
						window.innerHeight -
							visualViewport.height -
							visualViewport.offsetTop,
					)
				: 0;
			document.documentElement.style.setProperty(
				"--keyboard-inset",
				`${Math.round(inset)}px`,
			);
		};
		updateKeyboardInset();
		visualViewport?.addEventListener("resize", updateKeyboardInset);
		visualViewport?.addEventListener("scroll", updateKeyboardInset);
		window.addEventListener("resize", updateKeyboardInset);
		return () => {
			visualViewport?.removeEventListener("resize", updateKeyboardInset);
			visualViewport?.removeEventListener("scroll", updateKeyboardInset);
			window.removeEventListener("resize", updateKeyboardInset);
			document.documentElement.style.removeProperty("--keyboard-inset");
		};
	}, []);

	useEffect(() => {
		const modalBlocksShortcuts =
			Boolean(state.imageViewer?.open) || showModal || pendingDeleteId !== null;
		keybindingManager.clear();
		keybindingManager.register("Ctrl+N", () => {
			if (modalBlocksShortcuts) {
				return;
			}
			void store.createConversation();
			closeMobileSidebar();
		});
		keybindingManager.register("Ctrl+/", () => {
			if (modalBlocksShortcuts) {
				return;
			}
			if (isMobile) {
				setIsMobileSidebarActive((value) => !value);
				return;
			}
			setIsSidebarCollapsed((value) => !value);
		});
		keybindingManager.register("Ctrl+K", () => {
			if (modalBlocksShortcuts) {
				return;
			}
			requestComposerFocus(true);
		});
		keybindingManager.register("Ctrl+,", () => {
			if (modalBlocksShortcuts) {
				return;
			}
			setIsSettingsOpen(true);
		});
		keybindingManager.register("Escape", () => {
			if (state.imageViewer?.open) {
				closeImageViewer();
				return;
			}
			if (pendingDeleteId) {
				setPendingDeleteId(null);
				return;
			}
			if (isSettingsOpen && !needsSetup) {
				setIsSettingsOpen(false);
				return;
			}
			if (isMobileSidebarActive) {
				closeMobileSidebar();
			}
		});
		keybindingManager.startListening();
		return () => {
			keybindingManager.stopListening();
			keybindingManager.clear();
		};
	}, [
		closeMobileSidebar,
		closeImageViewer,
		isMobile,
		isMobileSidebarActive,
		isSettingsOpen,
		keybindingManager,
		needsSetup,
		pendingDeleteId,
		requestComposerFocus,
		showModal,
		state.imageViewer?.open,
		store,
	]);

	return (
		<AttachmentImageProvider client={client}>
			<main className="chat-app">
				{/* 移动端侧边栏背景遮罩 */}
				<div
					className={`sidebar-overlay ${isMobileSidebarActive ? "active" : ""}`}
					onClick={closeMobileSidebar}
					onKeyDown={(e) => {
						if (e.key === "Escape") closeMobileSidebar();
					}}
					role="presentation"
				/>

				{/* 侧边栏 */}
				<ConversationList
					id={CONVERSATION_SIDEBAR_ID}
					conversations={state.conversations}
					creating={state.creatingConversation}
					isCollapsed={!isMobile && isSidebarCollapsed}
					isMobileActive={isMobileSidebarActive}
					onCreate={() => {
						void store.createConversation().finally(() => {
							closeMobileSidebar();
						});
					}}
					onDelete={(conversationId) => setPendingDeleteId(conversationId)}
					onRename={(conversationId) => {
						const conversation = state.conversations.find(
							(item) => item.id === conversationId,
						);
						if (!conversation) return;

						const newTitle = window.prompt(
							"请输入新的会话名称：",
							conversation.title,
						);
						if (newTitle?.trim() && newTitle.trim() !== conversation.title) {
							void store.renameConversation(conversationId, newTitle.trim());
						}
					}}
					onOpenSettings={() => {
						closeMobileSidebar();
						setIsSettingsOpen(true);
					}}
					onSelect={(conversationId) => {
						void store.selectConversation(conversationId);
						closeMobileSidebar();
					}}
					onToggleCollapse={() => {
						if (isMobile) {
							closeMobileSidebar();
							return;
						}
						setIsSidebarCollapsed(true);
					}}
					selectedConversationId={selectedConversationId}
				/>

				{/* 主工作区 */}
				<section
					className="chat-workspace"
					aria-hidden={isMobile && isMobileSidebarActive ? true : undefined}
					aria-label="聊天"
				>
					{/* 顶栏 */}
					<header className="chat-topbar">
						<div className="topbar-left">
							{/* 侧边栏折叠时的展示按钮，或移动端的菜单按钮 */}
							{isSidebarCollapsed || isMobile ? (
								<button
									ref={mobileMenuButtonRef}
									aria-controls={isMobile ? CONVERSATION_SIDEBAR_ID : undefined}
									aria-expanded={isMobile ? isMobileSidebarActive : undefined}
									aria-label={isMobile ? "打开会话列表" : "展开菜单"}
									className="icon-button"
									onClick={() => {
										if (isMobile) {
											openMobileSidebar();
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
											setAllowInsecureStorageFallback(
												event.currentTarget.checked,
											)
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
						key={selectedConversationId ?? "none"}
						activeJob={activeJob}
						connectionState={state.connectionState}
						historyLoading={historyLoading}
						historyError={historyError}
						hasMoreHistory={selectedHistoryState?.hasMore ?? false}
						onRetryHistory={
							selectedConversationId
								? () => {
										void store.reloadHistory(selectedConversationId);
									}
								: undefined
						}
						onLoadMoreHistory={
							selectedConversationId
								? () => store.loadMoreHistory(selectedConversationId)
								: undefined
						}
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
						onAddReference={(messageId) => {
							if (selectedConversationId) {
								store.addReferenceFromMessageId(
									selectedConversationId,
									messageId,
								);
							}
						}}
						onOpenImage={openImage}
						onCancelJob={(jobId) => {
							void store.cancelJob(jobId);
						}}
					/>

					{/* 输入框 */}
					<MessageComposer
						attachmentQueue={
							selectedConversationId
								? (state.attachmentsByConversation[selectedConversationId] ??
									[])
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
						focusRequest={composerFocusRequest}
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
						onJumpReference={handleJumpReference}
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

				<ImageViewerModal
					imageViewer={state.imageViewer}
					onClose={closeImageViewer}
				/>

				<ConfirmDialog
					cancelLabel="取消"
					confirmLabel="删除"
					danger
					message={
						pendingDeleteConversation
							? `确定删除会话「${pendingDeleteConversation.title}」？该操作不可恢复。`
							: ""
					}
					onCancel={() => setPendingDeleteId(null)}
					onConfirm={() => {
						if (pendingDeleteId) {
							void store.deleteConversation(pendingDeleteId);
						}
						setPendingDeleteId(null);
					}}
					open={pendingDeleteConversation !== null}
					title="删除会话"
				/>
			</main>
		</AttachmentImageProvider>
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
