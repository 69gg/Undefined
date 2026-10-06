import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { createTauriRuntimeClient } from "../runtime-client/tauri";
import type { Attachment, HistoryResponse } from "../runtime-client/types";
import {
	conversation,
	historyItem,
	job,
	runtimeClientStub,
} from "../test-fixtures";
import { createChatStore } from "./store";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}

describe("Runtime instance isolation", () => {
	beforeEach(() => vi.resetAllMocks());

	test("a new Runtime sharing the default conversation sends only its own editor state through Tauri", async () => {
		const id = "legacy-system-42";
		let runtimeUrl = "http://runtime-a.example";
		let invokedOrigin = "";
		vi.mocked(invoke).mockImplementation(async () => {
			invokedOrigin = runtimeUrl;
			return {
				status: 202,
				ok: true,
				body: { job_id: "new", conversation_id: id },
			};
		});
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => ({ runtimeUrl, hasApiKey: true })),
			listConversations: vi.fn(async () => ({
				conversations: [conversation({ id })],
				activeJob: null,
				defaultConversationId: id,
				virtualUserId: "webchat",
			})),
			getHistory: vi.fn(async () => ({
				conversationId: id,
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 1,
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 1,
				items: [
					historyItem({
						messageId: runtimeUrl,
						role: "bot",
						content: runtimeUrl,
					}),
				],
			})),
			sendMessage: createTauriRuntimeClient().sendMessage,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft(id, "A private draft");
		store.addReferenceFromMessageId(id, runtimeUrl);
		await store.addAttachmentPath(id, "/mock/a-private.pdf");
		store.dispatch({ type: "autoScroll/set", enabled: false });
		runtimeUrl = "http://runtime-b.example";
		await store.bootstrap({ runtimeUrl });
		const state = store.getSnapshot();
		expect(state.draftsByConversation).toEqual({});
		expect(state.referencesByConversation).toEqual({});
		expect(state.attachmentsByConversation).toEqual({});
		expect(state.historyByConversation[id].items[0].content).toBe(runtimeUrl);
		expect(state.autoScrollEnabled).toBe(false);
		store.updateDraft(id, "B request");
		await store.sendSelectedMessage();
		expect(invokedOrigin).toBe(runtimeUrl);
		expect(invoke).toHaveBeenCalledWith("send_message", {
			input: {
				conversationId: id,
				message: { text: "B request", attachment_ids: [], references: [] },
			},
		});
	});

	test("reconnecting to the same Runtime preserves drafts, references, and ready attachments", async () => {
		const client = runtimeClientStub();
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "keep draft");
		store.addReference("default", { messageId: "a", quote: "keep quote" });
		await store.addAttachmentPath("default", "/mock/a.pdf");
		const before = store.getSnapshot();
		await store.bootstrap({
			runtimeUrl: before.runtimeConfig?.runtimeUrl,
			resuming: true,
		});
		const after = store.getSnapshot();
		expect(after.draftsByConversation).toEqual(before.draftsByConversation);
		expect(after.referencesByConversation).toEqual(
			before.referencesByConversation,
		);
		expect(after.attachmentsByConversation).toEqual(
			before.attachmentsByConversation,
		);
	});

	test("old history, uploads, and failed sends cannot repopulate a replacement Runtime", async () => {
		let runtimeUrl = "http://runtime-a.example";
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => ({ runtimeUrl, hasApiKey: true })),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		const history = deferred<HistoryResponse>();
		const upload = deferred<Attachment>();
		const send = deferred<ReturnType<typeof job>>();
		vi.mocked(client.getHistory).mockImplementationOnce(() => history.promise);
		vi.mocked(client.uploadAttachment).mockImplementationOnce(
			() => upload.promise,
		);
		vi.mocked(client.sendMessage).mockImplementationOnce(() => send.promise);
		store.updateDraft("default", "A pending send");
		const oldSend = store.sendSelectedMessage();
		const oldUpload = store.addAttachmentPath("default", "/mock/a.pdf");
		const oldHistory = store.reloadHistory("default");
		runtimeUrl = "http://runtime-b.example";
		await store.bootstrap({ runtimeUrl });
		store.updateDraft("default", "B new draft");
		history.resolve({
			conversationId: "default",
			virtualUserId: "webchat",
			permission: "superadmin",
			count: 1,
			limit: 50,
			before: null,
			hasMore: false,
			nextBefore: null,
			total: 1,
			items: [historyItem({ content: "A late history" })],
		});
		upload.resolve({
			id: "A-uid",
			name: "a.pdf",
			size: 1,
			mediaType: "application/pdf",
			kind: "file",
			downloadUrl: "",
			previewUrl: null,
			discarded: false,
		});
		send.reject(new Error("A late send failure"));
		await Promise.all([oldHistory, oldUpload, oldSend]);
		expect(store.getSnapshot().draftsByConversation.default).toBe(
			"B new draft",
		);
		expect(store.getSnapshot().attachmentsByConversation).toEqual({});
		expect(store.getSnapshot().historyByConversation.default.items).toEqual([]);
		expect(store.getSnapshot().sendError).toBeNull();
		await store.sendSelectedMessage();
		expect(client.sendMessage).toHaveBeenLastCalledWith({
			conversationId: "default",
			message: { text: "B new draft", attachmentIds: [], references: [] },
		});
	});

	test("a replacement Runtime preempts an old bootstrap and ignores its late SSE callback", async () => {
		let runtimeUrl = "http://runtime-a.example";
		const history = deferred<HistoryResponse>();
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => ({ runtimeUrl, hasApiKey: true })),
		});
		vi.mocked(client.getHistory).mockImplementationOnce(() => history.promise);
		const store = createChatStore({ client });
		const oldBootstrap = store.bootstrap();
		await vi.waitFor(() => expect(client.getHistory).toHaveBeenCalledTimes(1));
		const oldStatus = vi.mocked(client.listenRuntimeSse).mock.calls[0][1];
		runtimeUrl = "http://runtime-b.example";
		const newJob = job();
		vi.mocked(client.getActiveJobs).mockResolvedValue({
			job: newJob,
			jobs: [newJob],
		});
		await store.bootstrap({ runtimeUrl });
		oldStatus({
			subscriptionId: "old",
			jobId: newJob.jobId,
			status: "closed",
			detail: "late",
		});
		expect(client.fetchJobEventsJson).not.toHaveBeenCalled();
		history.resolve({
			conversationId: "default",
			virtualUserId: "webchat",
			permission: "superadmin",
			count: 1,
			limit: 50,
			before: null,
			hasMore: false,
			nextBefore: null,
			total: 1,
			items: [historyItem({ content: "A late bootstrap" })],
		});
		await oldBootstrap;
		expect(store.getSnapshot().runtimeConfig?.runtimeUrl).toBe(runtimeUrl);
		expect(store.getSnapshot().historyByConversation.default.items).toEqual([]);
		expect(store.getSnapshot().connectionState).toBe("streaming");
	});
});
