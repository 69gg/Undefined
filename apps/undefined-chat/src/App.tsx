import { open } from "@tauri-apps/plugin-dialog";
import {
	type ReactNode,
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
import { useTranslation } from "./i18n";
import { ImageViewerModal } from "./image-viewer/ImageViewerModal";
import { useImageViewer } from "./image-viewer/useImageViewer";
import { MessageComposer } from "./message-composer/MessageComposer";
import { MessageTimeline } from "./message-timeline/MessageTimeline";
import { setupAndroidLifecycle } from "./platform/AndroidLifecycle";
import { ConnectionSetup } from "./platform/ConnectionSetup";
import { DesktopLayout } from "./platform/DesktopLayout";
import { KeybindingManager } from "./platform/KeybindingManager";
import {
	isAndroidPlatform,
	isDesktopPlatform,
	isMobilePlatform,
	usePlatform,
} from "./platform/PlatformContext";
import { AttachmentImageProvider } from "./rendering/AttachmentImageContext";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import type { Attachment } from "./runtime-client/types";
import { useTheme } from "./theme/use-theme";
import { isImageAttachment } from "./utils/attachment";

const CONVERSATION_SIDEBAR_ID = "conversation-sidebar";
/** 焦点可聚焦元素选择器（用于移动端抽屉焦点陷阱与初始聚焦） */
const FOCUSABLE_SELECTOR =
	"button, [href], input, textarea, select, [tabindex]:not([tabindex='-1'])";

export function App() {
	const { t } = useTranslation();
	const platform = usePlatform();
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
	// 窄视口或真实移动平台均视为移动端：解决平板/移动设备横屏（>768px）被误判为桌面
	const isNarrowViewport = useMediaQuery("(max-width: 768px)");
	const isMobile = isNarrowViewport || isMobilePlatform(platform);

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

	const [setupError, setSetupError] = useState<string | null>(null);

	const needsSetup =
		!state.runtimeConfig?.runtimeUrl || !state.runtimeConfig.hasApiKey;

	useEffect(() => {
		// 首次挂载：不传 preserveSelectionId，走后端默认选中逻辑
		void store.bootstrap();
	}, [store]);

	useEffect(() => {
		// 以真实平台为准启用 Android 生命周期（替代旧的 UA 判定）
		if (!isAndroidPlatform(platform)) {
			return undefined;
		}
		return setupAndroidLifecycle(store);
	}, [store, platform]);

	// 应用主题到 DOM
	useEffect(() => {
		document.documentElement.dataset.theme = effectiveTheme;
	}, [effectiveTheme]);

	// 窗口聚焦时按 TTL 刷新命令列表，使 Skills 热重载新增命令可见
	useEffect(() => {
		const onFocus = (): void => {
			void store.refreshCommandsIfStale();
		};
		window.addEventListener("focus", onFocus);
		return () => {
			window.removeEventListener("focus", onFocus);
		};
	}, [store]);

	async function handleConnect(
		url: string,
		apiKey: string,
		allowInsecure: boolean,
	): Promise<void> {
		setSetupError(null);
		try {
			await client.saveRuntimeConfig(url);
			if (allowInsecure) {
				await client.confirmInsecureStorageFallback();
			}
			// settings 模式下密钥留空表示沿用原密钥，仅在有输入时保存
			if (apiKey) {
				await client.saveApiKey(apiKey);
			}
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
				window.alert(result.body ?? t("attachment.saveFailed"));
				return;
			}
			window.alert(
				t("attachment.saved", {
					name: result.savedFileName ?? attachment.name,
				}),
			);
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
				window.alert(result.body ?? t("attachment.previewFailed"));
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
				title: t("attachment.pickerTitle"),
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
						window.alert(t("reference.notLoaded"));
					}
				});
			});
			return;
		}
		window.alert(t("reference.notInHistory"));
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
			const firstControl =
				sidebar?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
			firstControl?.focus();
		});
	}, [isMobile, isMobileSidebarActive]);

	// 移动端抽屉打开时的焦点陷阱：Tab / Shift+Tab 循环限制在 #conversation-sidebar 内
	// 配合 P-misc 给抽屉容器加的 role="dialog" aria-modal="true"
	useEffect(() => {
		if (!isMobile || !isMobileSidebarActive) {
			return undefined;
		}
		const handleKeyDown = (event: KeyboardEvent): void => {
			if (event.key !== "Tab") {
				return;
			}
			const sidebar = document.getElementById(CONVERSATION_SIDEBAR_ID);
			if (!sidebar) {
				return;
			}
			const focusable = Array.from(
				sidebar.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
			).filter(
				(element) =>
					!element.hasAttribute("disabled") && element.offsetParent !== null,
			);
			if (focusable.length === 0) {
				return;
			}
			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			const active = document.activeElement as HTMLElement | null;
			// 焦点已离开抽屉（或在边界）时，循环回到另一端
			if (event.shiftKey) {
				if (active === first || !sidebar.contains(active)) {
					event.preventDefault();
					last?.focus();
				}
			} else if (active === last || !sidebar.contains(active)) {
				event.preventDefault();
				first?.focus();
			}
		};
		document.addEventListener("keydown", handleKeyDown, true);
		return () => {
			document.removeEventListener("keydown", handleKeyDown, true);
		};
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
							t("conversation.renamePrompt"),
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

				{/* 主工作区（桌面端用 DesktopLayout 透明包裹，预留平台增强位） */}
				<section
					className="chat-workspace"
					aria-hidden={isMobile && isMobileSidebarActive ? true : undefined}
					aria-label={t("app.workspace.aria")}
				>
					<WorkspaceLayout isDesktop={isDesktopPlatform(platform)}>
						{/* 顶栏 */}
						<header className="chat-topbar">
							<div className="topbar-left">
								{/* 侧边栏折叠时的展示按钮，或移动端的菜单按钮 */}
								{isSidebarCollapsed || isMobile ? (
									<button
										ref={mobileMenuButtonRef}
										aria-controls={
											isMobile ? CONVERSATION_SIDEBAR_ID : undefined
										}
										aria-expanded={isMobile ? isMobileSidebarActive : undefined}
										aria-label={
											isMobile
												? t("app.topbar.openConversations")
												: t("app.topbar.expandMenu")
										}
										className="icon-button"
										onClick={() => {
											if (isMobile) {
												openMobileSidebar();
											} else {
												setIsSidebarCollapsed(false);
											}
										}}
										title={t("app.topbar.expandMenu")}
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
											<title>{t("app.topbar.expandMenu")}</title>
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
										)?.title || t("app.topbar.defaultConversation")}
									</strong>
									<div
										style={{ display: "flex", gap: "6px", marginTop: "2px" }}
									>
										<span
											className={`connection-pill ${state.connectionState}`}
										>
											{t(`app.connection.${state.connectionState}`)}
										</span>
									</div>
								</div>
							</div>

							<div className="runtime-indicator">
								<span>{state.runtimeConfig?.runtimeUrl ?? "Runtime"}</span>
							</div>
						</header>

						{/* 模态框 / 配置面板：统一 ConnectionSetup（首次连接 / 运行期修改两种模式） */}
						{showModal ? (
							<ConnectionSetup
								mode={needsSetup ? "setup" : "settings"}
								currentUrl={state.runtimeConfig?.runtimeUrl}
								onConnect={(url, apiKey, allowInsecure) => {
									void handleConnect(url, apiKey, allowInsecure);
								}}
								onClose={
									needsSetup ? undefined : () => setIsSettingsOpen(false)
								}
								error={setupError}
							>
								{/* settings 模式下附带自动滚动偏好开关 */}
								{!needsSetup ? (
									<label className="setup-checkbox">
										<input
											checked={state.autoScrollEnabled}
											onChange={(event) =>
												store.dispatch({
													type: "autoScroll/set",
													enabled: event.currentTarget.checked,
												})
											}
											type="checkbox"
										/>
										<span>{t("settings.autoScroll")}</span>
									</label>
								) : null}
							</ConnectionSetup>
						) : state.error ? (
							<p className="app-error">{t(state.error)}</p>
						) : null}

						{/* 消息时间线 */}
						<MessageTimeline
							key={selectedConversationId ?? "none"}
							activeJob={activeJob}
							autoScrollEnabled={state.autoScrollEnabled}
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
							onAddSelectionReference={(text) => {
								if (selectedConversationId) {
									store.addReferenceFromSelection(selectedConversationId, text);
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
									? (state.referencesByConversation[selectedConversationId] ??
										[])
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
							<p className="app-error">{t(state.sendError)}</p>
						) : null}
					</WorkspaceLayout>
				</section>

				<ImageViewerModal
					imageViewer={state.imageViewer}
					onClose={closeImageViewer}
				/>

				<ConfirmDialog
					cancelLabel={t("dialog.cancel")}
					confirmLabel={t("dialog.delete")}
					danger
					message={
						pendingDeleteConversation
							? t("dialog.deleteConversationMessage", {
									title: pendingDeleteConversation.title,
								})
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
					title={t("dialog.deleteConversationTitle")}
				/>
			</main>
		</AttachmentImageProvider>
	);
}

/**
 * 主工作区布局包装：桌面平台用 DesktopLayout（透明 display:contents 包装，
 * 预留自定义标题栏 / 原生菜单等增强位），其它平台直接渲染子节点。
 */
function WorkspaceLayout({
	isDesktop,
	children,
}: {
	isDesktop: boolean;
	children: ReactNode;
}) {
	return isDesktop ? (
		<DesktopLayout>{children}</DesktopLayout>
	) : (
		<>{children}</>
	);
}
