import { describe, expect, test, vi } from "vitest";
import { conversation, runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

describe("conversation rename", () => {
	test.each([false, true])(
		"keeps the current conversation during rename (switch while pending: %s)",
		async (switchWhilePending) => {
			let finishRename!: (value: { ok: boolean }) => void;
			const client = runtimeClientStub({
				listConversations: vi.fn(async () => ({
					conversations: [conversation({ id: "A" }), conversation({ id: "B" })],
					activeJob: null,
					defaultConversationId: "A",
					virtualUserId: "webchat",
				})),
				renameConversation: vi.fn(
					() =>
						new Promise<{ ok: boolean }>((resolve) => {
							finishRename = resolve;
						}),
				),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			if (!switchWhilePending) await store.selectConversation("B");
			const rename = store.renameConversation("A", "Renamed A");
			if (switchWhilePending) await store.selectConversation("B");
			store.updateDraft("B", "B draft");
			store.dispatch({ type: "mobile-panel/set", panel: "conversations" });
			finishRename({ ok: true });
			await rename;
			expect(store.getSnapshot().selectedConversationId).toBe("B");
			expect(store.getSnapshot().settings.mobilePanel).toBe("conversations");
			expect(store.getSnapshot().draftsByConversation.B).toBe("B draft");
			expect(
				store.getSnapshot().conversations.find((item) => item.id === "A")
					?.title,
			).toBe("Renamed A");
			await store.sendSelectedMessage();
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "B",
				message: {
					text: "B draft",
					attachmentIds: [],
					references: [],
				},
			});
		},
	);
});
