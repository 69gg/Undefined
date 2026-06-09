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
import { MessageComposer } from "./message-composer/MessageComposer";
import { MessageTimeline } from "./message-timeline/MessageTimeline";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import type { Attachment } from "./runtime-client/types";

export function App() {
	const client = useMemo(() => createTauriRuntimeClient(), []);
	const store = useMemo(() => createChatStore({ client }), [client]);
	const state = useSyncExternalStore(
		store.subscribe,
		store.getSnapshot,
		store.getSnapshot,
	);
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
		state.runtimeConfig?.runtimeUrl ?? "http://127.0.0.1:8080",
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

	return (
		<main className="chat-app">
			<ConversationList
				conversations={state.conversations}
				selectedConversationId={selectedConversationId}
				onCreate={() => {
					void store.createConversation();
				}}
				onSelect={(conversationId) => {
					void store.selectConversation(conversationId);
				}}
			/>
			<section className="chat-workspace" aria-label="聊天">
				<header className="chat-topbar">
					<button className="mobile-rail-button" type="button">
						会话
					</button>
					<div className="chat-title-block">
						<strong>
							{state.conversations.find(
								(item) => item.id === selectedConversationId,
							)?.title ?? "默认会话"}
						</strong>
						<span>{connectionStateLabel(state.connectionState)}</span>
					</div>
					<div className="runtime-indicator">
						<span>{state.runtimeConfig?.runtimeUrl ?? "Runtime"}</span>
					</div>
				</header>
				{needsSetup ? (
					<form className="setup-panel" onSubmit={handleSetupSubmit}>
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
								onChange={(event) => setSetupApiKey(event.currentTarget.value)}
								required
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
						{setupError ? <strong>{setupError}</strong> : null}
					</form>
				) : state.error ? (
					<p className="app-error">{state.error}</p>
				) : null}
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
				/>
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
