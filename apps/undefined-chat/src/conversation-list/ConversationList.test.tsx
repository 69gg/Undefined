import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { conversation } from "../test-fixtures";
import { ConversationList } from "./ConversationList";

describe("ConversationList", () => {
	test("renders multiple running states and selects conversations", async () => {
		const onSelect = vi.fn();

		render(
			<ConversationList
				conversations={[
					conversation({
						id: "default",
						title: "默认会话",
						isRunning: true,
						messageCount: 12,
					}),
					conversation({
						id: "ops",
						title: "运维排障",
						isRunning: true,
						messageCount: 3,
					}),
					conversation({
						id: "ideas",
						title: "想法",
						isRunning: false,
						messageCount: 1,
					}),
				]}
				selectedConversationId="default"
				onCreate={vi.fn()}
				onSelect={onSelect}
			/>,
		);

		expect(screen.getByRole("navigation", { name: "会话" })).toBeTruthy();
		expect(screen.getAllByText("运行中")).toHaveLength(2);
		expect(screen.getByText("12 条消息")).toBeTruthy();

		await userEvent.click(screen.getByRole("button", { name: /运维排障/ }));

		expect(onSelect).toHaveBeenCalledWith("ops");
	});
});
