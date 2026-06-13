import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import type { CommandInfo } from "../runtime-client/types";
import { CommandPalette } from "./CommandPalette";

describe("CommandPalette", () => {
	const mockCommands: CommandInfo[] = [
		{ name: "help", description: "显示帮助信息" },
		{ name: "version", description: "显示版本号" },
		{ name: "history", description: "查看历史记录" },
		{ name: "clear", description: "清空会话" },
	];

	test("renders nothing when closed", () => {
		const { container } = render(
			<CommandPalette
				open={false}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		expect(container.firstChild).toBeNull();
	});

	test("renders nothing when no matches", () => {
		const { container } = render(
			<CommandPalette
				open={true}
				query="xyz"
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		expect(container.firstChild).toBeNull();
	});

	test("renders all commands when query is empty", () => {
		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		expect(screen.getByText("/help")).toBeInTheDocument();
		expect(screen.getByText("/version")).toBeInTheDocument();
		expect(screen.getByText("/history")).toBeInTheDocument();
		expect(screen.getByText("/clear")).toBeInTheDocument();
	});

	test("filters commands by query", () => {
		render(
			<CommandPalette
				open={true}
				query="he"
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		expect(screen.getByText("/help")).toBeInTheDocument();
		expect(screen.queryByText("/version")).not.toBeInTheDocument();
	});

	test("highlights active item", () => {
		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={1}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		const items = screen.getAllByRole("option");
		expect(items[0]).not.toHaveClass("active");
		expect(items[1]).toHaveClass("active");
	});

	test("calls onSelect when clicking an item", async () => {
		const onSelect = vi.fn();

		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={onSelect}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		await userEvent.click(screen.getByText("/help"));
		expect(onSelect).toHaveBeenCalledWith(mockCommands[0]);
	});

	test("calls onNavigate on ArrowUp/ArrowDown", async () => {
		const onNavigate = vi.fn();

		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={onNavigate}
			/>,
		);

		const palette = screen.getByRole("listbox");
		palette.focus();

		await userEvent.keyboard("{ArrowDown}");
		expect(onNavigate).toHaveBeenCalledWith(1);

		await userEvent.keyboard("{ArrowUp}");
		expect(onNavigate).toHaveBeenCalledWith(-1);
	});

	test("calls onSelect on Enter", async () => {
		const onSelect = vi.fn();

		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={onSelect}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		const palette = screen.getByRole("listbox");
		palette.focus();

		await userEvent.keyboard("{Enter}");
		expect(onSelect).toHaveBeenCalledWith(mockCommands[0]);
	});

	test("calls onClose on Escape", async () => {
		const onClose = vi.fn();

		render(
			<CommandPalette
				open={true}
				query=""
				commands={mockCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={onClose}
				onNavigate={vi.fn()}
			/>,
		);

		const palette = screen.getByRole("listbox");
		palette.focus();

		await userEvent.keyboard("{Escape}");
		expect(onClose).toHaveBeenCalledOnce();
	});

	test("sorts commands by score", () => {
		const commands: CommandInfo[] = [
			{ name: "test", description: "完全匹配" },
			{ name: "testing", description: "前缀匹配" },
			{ name: "attest", description: "包含匹配" },
		];

		render(
			<CommandPalette
				open={true}
				query="test"
				commands={commands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		const items = screen.getAllByRole("option");
		// 完全匹配应该排第一
		expect(items[0]).toHaveTextContent("/test");
		// 前缀匹配应该排第二
		expect(items[1]).toHaveTextContent("/testing");
		// 包含匹配应该排第三
		expect(items[2]).toHaveTextContent("/attest");
	});

	test("limits results to MAX_MATCHES (8)", () => {
		const manyCommands: CommandInfo[] = Array.from({ length: 15 }, (_, i) => ({
			name: `cmd${i}`,
			description: `命令 ${i}`,
		}));

		render(
			<CommandPalette
				open={true}
				query=""
				commands={manyCommands}
				activeIndex={0}
				onSelect={vi.fn()}
				onClose={vi.fn()}
				onNavigate={vi.fn()}
			/>,
		);

		const items = screen.getAllByRole("option");
		expect(items).toHaveLength(8);
	});
});
