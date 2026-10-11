import { describe, expect, test, vi } from "vitest";
import type { Attachment, RuntimeConfig } from "../runtime-client/types";
import { runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}

const uploaded: Attachment = {
	id: "file-A",
	name: "A.txt",
	size: 4,
	kind: "file",
	mediaType: "text/plain",
	downloadUrl: "/attachment/file-A",
	previewUrl: null,
	discarded: false,
};

describe("attachment uploads across connection settings suspension", () => {
	test.each(["success", "failure"])(
		"settles late %s uploads according to the connection boundary",
		async (outcome) => {
			for (const boundary of [
				"resume",
				"same",
				"different",
				"completed",
			] as const) {
				let config: RuntimeConfig = {
					runtimeUrl: "http://runtime-a.test",
					hasApiKey: true,
				};
				const pending = deferred<Attachment>();
				const client = runtimeClientStub({
					getRuntimeConfig: vi.fn(async () => config),
					uploadAttachment: vi.fn(async () => pending.promise),
				});
				const store = createChatStore({ client });
				await store.bootstrap();
				const uploading = store.addAttachmentPath("default", "/isolated/A.txt");
				const finish = () =>
					outcome === "success"
						? pending.resolve(uploaded)
						: pending.reject(new Error("upload-failed"));
				if (boundary === "completed") {
					finish();
					await uploading;
				}
				if (boundary !== "resume") store.suspendRuntime();
				if (boundary === "different")
					config = { ...config, runtimeUrl: "http://runtime-b.test" };
				await store.bootstrap({ resuming: true, resumeSuspended: true });
				if (boundary !== "completed") {
					finish();
					await uploading;
				}
				const queue =
					store.getSnapshot().attachmentsByConversation.default ?? [];
				expect(queue.map((item) => item.status)).toEqual(
					boundary === "different"
						? []
						: [
								boundary === "same"
									? "error"
									: outcome === "success"
										? "ready"
										: "error",
							],
				);
				if (boundary === "same") {
					expect(queue[0].error).toBe("error.attachmentsFailed");
					store.updateDraft("default", "send");
					await store.sendSelectedMessage();
					expect(store.getSnapshot().sendError).toBe("error.attachmentsFailed");
					expect(client.sendMessage).not.toHaveBeenCalled();
				}
			}
		},
	);

	test.each(["success", "failure"])(
		"removed uploads cannot reappear after late %s responses",
		async (outcome) => {
			for (const suspended of [false, true]) {
				const pending = deferred<Attachment>();
				const client = runtimeClientStub({
					uploadAttachment: vi
						.fn()
						.mockImplementationOnce(() => pending.promise)
						.mockResolvedValue({ ...uploaded, id: "reselected" }),
				});
				const store = createChatStore({ client });
				await store.bootstrap();
				const old = store.addAttachmentPath("default", "/isolated/A.txt");
				if (suspended) store.suspendRuntime();
				const id = store.getSnapshot().attachmentsByConversation.default[0].id;
				store.clearAttachment("default", id);
				if (suspended) await store.bootstrap({ resumeSuspended: true });
				await store.addAttachmentPath("default", "/isolated/A.txt");
				if (outcome === "success") pending.resolve(uploaded);
				else pending.reject(new Error("obsolete upload failure"));
				await old;
				expect(
					store.getSnapshot().attachmentsByConversation.default,
				).toHaveLength(1);
				expect(
					store.getSnapshot().attachmentsByConversation.default[0].attachmentId,
				).toBe("reselected");
				store.updateDraft("default", "send-after-reselect");
				await store.sendSelectedMessage();
				expect(client.sendMessage).toHaveBeenCalledWith({
					conversationId: "default",
					message: {
						text: "send-after-reselect",
						attachmentIds: ["reselected"],
						references: [],
					},
				});
			}
		},
	);
});
