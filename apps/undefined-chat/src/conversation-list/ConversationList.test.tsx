import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { conversation } from "../test-fixtures";
import { ConversationList } from "./ConversationList";

const baseConversations = [
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
];

describe("ConversationList", () => {
	test("renders multiple running states and selects conversations", async () => {
		const onSelect = vi.fn();

		render(
			<ConversationList
				conversations={baseConversations}
				creating={false}
				selectedConversationId="default"
				onCreate={vi.fn()}
				onDelete={vi.fn()}
				onSelect={onSelect}
				isCollapsed={false}
				onToggleCollapse={vi.fn()}
				onOpenSettings={vi.fn()}
			/>,
		);

		expect(screen.getByRole("navigation", { name: "会话" })).toBeTruthy();
		expect(screen.getAllByText("运行中")).toHaveLength(2);
		expect(screen.getByText("12 条消息")).toBeTruthy();

		await userEvent.click(screen.getByRole("button", { name: /运维排障/ }));

		expect(onSelect).toHaveBeenCalledWith("ops");
	});

	test("每个会话项有删除按钮，点击触发 onDelete", async () => {
		const onDelete = vi.fn();

		render(
			<ConversationList
				conversations={baseConversations}
				creating={false}
				selectedConversationId="default"
				onCreate={vi.fn()}
				onDelete={onDelete}
				onSelect={vi.fn()}
				isCollapsed={false}
				onToggleCollapse={vi.fn()}
				onOpenSettings={vi.fn()}
			/>,
		);

		const deleteButtons = screen.getAllByRole("button", { name: "删除会话" });
		expect(deleteButtons).toHaveLength(3);
		// 第二个会话（运维排障）的删除按钮
		await userEvent.click(deleteButtons[1]);
		expect(onDelete).toHaveBeenCalledWith("ops");
	});

	test("正在新建时按钮显示加载态并禁用", () => {
		render(
			<ConversationList
				conversations={baseConversations}
				creating={true}
				selectedConversationId="default"
				onCreate={vi.fn()}
				onDelete={vi.fn()}
				onSelect={vi.fn()}
				isCollapsed={false}
				onToggleCollapse={vi.fn()}
				onOpenSettings={vi.fn()}
			/>,
		);

		const newButton = screen.getByRole("button", { name: /正在新建/ });
		expect(newButton).toBeDisabled();
	});
});
