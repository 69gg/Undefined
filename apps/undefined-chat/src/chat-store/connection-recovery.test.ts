import { describe, expect, test, vi } from "vitest";
import type { RuntimeConfig } from "../runtime-client/types";
import { runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

describe("connection configuration suspension", () => {
	test("blocks Runtime operations and lifecycle bootstrap until explicit connection recovery", async () => {
		let runtimeConfig: RuntimeConfig = {
			runtimeUrl: "http://runtime-a.test",
			hasApiKey: true,
		};
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => runtimeConfig),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "A draft");
		store.suspendRuntime();
		await Promise.all([
			store.sendSelectedMessage(),
			store.createConversation(),
			store.deleteConversation("default"),
			store.renameConversation("default", "unsafe rename"),
			store.selectConversation("default"),
			store.addAttachmentPath("default", "/mock/a.txt"),
			store.reloadHistory("default"),
			store.loadMoreHistory("default"),
			store.cancelJob("job-1"),
			store.refreshCommandsIfStale(),
			store.bootstrap({ resuming: true }),
		]);
		expect(client.sendMessage).not.toHaveBeenCalled();
		expect(client.createConversation).not.toHaveBeenCalled();
		expect(client.deleteConversation).not.toHaveBeenCalled();
		expect(client.renameConversation).not.toHaveBeenCalled();
		expect(client.uploadAttachment).not.toHaveBeenCalled();
		expect(client.cancelJob).not.toHaveBeenCalled();
		expect(client.getHistory).toHaveBeenCalledTimes(1);
		expect(client.listCommands).toHaveBeenCalledTimes(1);
		expect(client.getRuntimeConfig).toHaveBeenCalledTimes(1);
		expect(store.getSnapshot().draftsByConversation.default).toBe("A draft");
		await store.bootstrap({ resumeSuspended: true });
		await store.sendSelectedMessage();
		expect(client.sendMessage).toHaveBeenCalledWith({
			conversationId: "default",
			message: { text: "A draft", attachmentIds: [], references: [] },
		});
		runtimeConfig = { ...runtimeConfig, runtimeUrl: "http://runtime-b.test" };
		store.suspendRuntime(runtimeConfig);
		expect(store.getSnapshot().runtimeConfig).toEqual(runtimeConfig);
		expect(store.getSnapshot().conversations).toEqual([]);
		expect(store.getSnapshot().draftsByConversation).toEqual({});
		expect(store.getSnapshot().connectionState).toBe("disconnected");
		await store.bootstrap();
		expect(client.getRuntimeConfig).toHaveBeenCalledTimes(2);
		await store.bootstrap({ resumeSuspended: true });
		expect(store.getSnapshot().runtimeConfig).toEqual(runtimeConfig);
		expect(store.getSnapshot().connectionState).toBe("connected");
	});
});
