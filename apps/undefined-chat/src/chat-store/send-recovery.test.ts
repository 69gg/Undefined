import { describe, expect, test, vi } from "vitest";
import type { Attachment, RuntimeClient } from "../runtime-client/types";
import { conversation, job, runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((done, fail) => {
		resolve = done;
		reject = fail;
	});
	return { promise, resolve, reject };
}

function attachment(id: string): Attachment {
	return {
		id,
		name: `${id}.txt`,
		size: 4,
		mediaType: "text/plain",
		kind: "file",
		downloadUrl: null,
		previewUrl: null,
		discarded: false,
	};
}

describe("send failure recovery", () => {
	test.each(["new draft", ""])(
		"preserves later text edits including an intentional empty draft (%j)",
		async (laterDraft) => {
			const sent = deferred<never>();
			const client = runtimeClientStub({
				sendMessage: vi
					.fn<RuntimeClient["sendMessage"]>()
					.mockImplementationOnce(() => sent.promise)
					.mockResolvedValueOnce(job()),
				uploadAttachment: vi.fn(async () => attachment("file_a")),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("default", "  first message  ");
			store.addReference("default", { messageId: "a", quote: "first quote" });
			await store.addAttachmentPath("default", "/mock/a.txt");
			const original = store.getSnapshot();
			const sending = store.sendSelectedMessage();
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "default",
				message: {
					text: "first message",
					attachmentIds: ["file_a"],
					references: [{ messageId: "a", quote: "first quote" }],
				},
			});
			store.updateDraft("default", "typed after sending");
			store.updateDraft("default", laterDraft);
			sent.reject(new Error("POST failed"));
			await sending;
			const state = store.getSnapshot();
			expect(state.draftsByConversation.default).toBe(laterDraft);
			expect(state.attachmentsByConversation.default).toEqual(
				original.attachmentsByConversation.default,
			);
			expect(state.referencesByConversation.default).toEqual(
				original.referencesByConversation.default,
			);
			expect(
				state.historyByConversation.default.items.some(
					(item) => item.content === "first message",
				),
			).toBe(false);
			expect(state.sendError).toBe("POST failed");
			await store.sendSelectedMessage();
			expect(client.sendMessage).toHaveBeenLastCalledWith({
				conversationId: "default",
				message: {
					text: laterDraft,
					attachmentIds: ["file_a"],
					references: [{ messageId: "a", quote: "first quote" }],
				},
			});
		},
	);

	test("preserves a new pending attachment and a new reference while restoring unchanged text", async () => {
		const sent = deferred<never>();
		const uploaded = deferred<Attachment>();
		const client = runtimeClientStub({
			sendMessage: vi.fn(() => sent.promise),
			uploadAttachment: vi
				.fn()
				.mockResolvedValueOnce(attachment("file_a"))
				.mockImplementationOnce(() => uploaded.promise),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "  unchanged text  ");
		store.addReference("default", { messageId: "a", quote: "old quote" });
		await store.addAttachmentPath("default", "/mock/a.txt");
		const sending = store.sendSelectedMessage();
		const uploading = store.addAttachmentPath("default", "/mock/b.txt");
		store.addReference("default", { messageId: "b", quote: "new quote" });
		const edited = store.getSnapshot();
		sent.reject(new Error("POST failed"));
		await sending;
		expect(store.getSnapshot().draftsByConversation.default).toBe(
			"  unchanged text  ",
		);
		expect(store.getSnapshot().attachmentsByConversation.default).toEqual(
			edited.attachmentsByConversation.default,
		);
		expect(store.getSnapshot().referencesByConversation.default).toEqual([
			{ messageId: "b", quote: "new quote" },
		]);
		uploaded.resolve(attachment("file_b"));
		await uploading;
		expect(store.getSnapshot().attachmentsByConversation.default).toMatchObject(
			[{ name: "file_b.txt", status: "ready", attachmentId: "file_b" }],
		);
	});

	test("does not restore attachments or references after they were edited then cleared", async () => {
		const sent = deferred<never>();
		const client = runtimeClientStub({
			sendMessage: vi.fn(() => sent.promise),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "keep original");
		store.addReference("default", { messageId: "a", quote: "old quote" });
		await store.addAttachmentPath("default", "/mock/a.txt");
		const sending = store.sendSelectedMessage();
		await store.addAttachmentPath("default", "/mock/b.txt");
		const newAttachment =
			store.getSnapshot().attachmentsByConversation.default[0];
		store.clearAttachment("default", newAttachment.id);
		store.addReference("default", { messageId: "b", quote: "new quote" });
		store.clearReference("default", "b");
		sent.reject(new Error("POST failed"));
		await sending;
		expect(store.getSnapshot().draftsByConversation.default).toBe(
			"keep original",
		);
		expect(store.getSnapshot().attachmentsByConversation.default).toEqual([]);
		expect(store.getSnapshot().referencesByConversation.default).toEqual([]);
	});

	test("editing another conversation still restores this conversation's unchanged fields", async () => {
		const sent = deferred<never>();
		const client = runtimeClientStub({
			sendMessage: vi.fn(() => sent.promise),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "  exact original  ");
		const sending = store.sendSelectedMessage();
		store.updateDraft("other", "other conversation draft");
		sent.reject(new Error("POST failed"));
		await sending;
		expect(store.getSnapshot().draftsByConversation.default).toBe(
			"  exact original  ",
		);
		expect(store.getSnapshot().draftsByConversation.other).toBe(
			"other conversation draft",
		);
	});

	test.each(["attachments", "references"])(
		"an edited %s field does not stop restoration of the other unchanged field",
		async (editedField) => {
			const sent = deferred<never>();
			const client = runtimeClientStub({
				sendMessage: vi.fn(() => sent.promise),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("default", "original draft");
			store.addReference("default", { messageId: "a", quote: "old quote" });
			await store.addAttachmentPath("default", "/mock/a.txt");
			const original = store.getSnapshot();
			const sending = store.sendSelectedMessage();
			if (editedField === "attachments") {
				await store.addAttachmentPath("default", "/mock/b.txt");
			} else {
				store.addReference("default", { messageId: "b", quote: "new quote" });
			}
			const edited = store.getSnapshot();
			sent.reject(new Error("POST failed"));
			await sending;
			const recovered = store.getSnapshot();
			expect(recovered.attachmentsByConversation.default).toEqual(
				editedField === "attachments"
					? edited.attachmentsByConversation.default
					: original.attachmentsByConversation.default,
			);
			expect(recovered.referencesByConversation.default).toEqual(
				editedField === "references"
					? edited.referencesByConversation.default
					: original.referencesByConversation.default,
			);
		},
	);

	test.each([false, true])(
		"removing a conversation clears its revision and rejects stale recovery (reimport=%s)",
		async (reimport) => {
			const sent = deferred<never>();
			const client = runtimeClientStub({
				sendMessage: vi.fn(() => sent.promise),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("default", "deleted draft");
			const sending = store.sendSelectedMessage();
			await store.deleteConversation("default");
			if (reimport) {
				// 同名会话重新导入并两次编辑，也不能复用已删除会话的旧修订。
				store.dispatch({
					type: "conversation/upsert",
					conversation: conversation(),
				});
				store.updateDraft("default", "new draft");
				store.updateDraft("default", "");
			}
			sent.reject(new Error("POST failed"));
			await sending;
			expect(store.getSnapshot().draftsByConversation.default).toBe(
				reimport ? "" : undefined,
			);
			expect(
				store.getSnapshot().attachmentsByConversation.default,
			).toBeUndefined();
			expect(
				store.getSnapshot().referencesByConversation.default,
			).toBeUndefined();
		},
	);
});
