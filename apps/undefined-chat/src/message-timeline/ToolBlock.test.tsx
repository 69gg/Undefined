import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import { ToolBlock } from "./ToolBlock";

describe("ToolBlock", () => {
	it("renders tool name and status", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-1",
			toolName: "test_tool",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		render(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("test_tool")).toBeInTheDocument();
		expect(screen.getByText("完成")).toBeInTheDocument();
	});

	it("displays running status with correct styling", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-2",
			toolName: "running_tool",
			status: "running",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 500,
		};

		const { container } = render(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("运行中")).toBeInTheDocument();
		const details = container.querySelector(".runtime-tool-block");
		expect(details).toHaveClass("running");
	});

	it("displays error status with correct styling", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-3",
			toolName: "failed_tool",
			status: "error",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 2000,
			endTime: Date.now(),
		};

		const { container } = render(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("失败")).toBeInTheDocument();
		const details = container.querySelector(".runtime-tool-block");
		expect(details).toHaveClass("error");
	});

	it("formats duration correctly", () => {
		const startTime = Date.now() - 1500;
		const endTime = Date.now();

		const toolBlock: ToolBlockType = {
			webchatCallId: "call-4",
			toolName: "timed_tool",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime,
			endTime,
		};

		render(<ToolBlock {...toolBlock} />);

		// Should display duration in seconds
		const durationElement = screen.getByText(/1\.[0-9]s/);
		expect(durationElement).toBeInTheDocument();
	});

	it("toggles expansion when clicked", async () => {
		const user = userEvent.setup();

		const toolBlock: ToolBlockType = {
			webchatCallId: "call-5",
			toolName: "expandable_tool",
			status: "done",
			children: new Map(),
			timeline: [
				{
					type: "input",
					timestamp: Date.now() - 1000,
					content: "test input",
				},
			],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = render(<ToolBlock {...toolBlock} />);

		const details = container.querySelector("details");
		expect(details).not.toHaveAttribute("open");

		const summary = screen.getByText("expandable_tool").closest("summary");
		if (summary) {
			await user.click(summary);
		}

		expect(details).toHaveAttribute("open");
	});

	it("renders timeline entries", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-6",
			toolName: "tool_with_timeline",
			status: "done",
			children: new Map(),
			timeline: [
				{
					type: "input",
					timestamp: Date.now() - 2000,
					content: "input content",
				},
				{
					type: "output",
					timestamp: Date.now() - 1000,
					content: "output content",
				},
				{
					type: "error",
					timestamp: Date.now() - 500,
					message: "error message",
				},
			],
			startTime: Date.now() - 2000,
			endTime: Date.now(),
		};

		render(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("input content")).toBeInTheDocument();
		expect(screen.getByText("output content")).toBeInTheDocument();
		expect(screen.getByText("error message")).toBeInTheDocument();
	});

	it("renders nested children recursively", () => {
		const childBlock: ToolBlockType = {
			webchatCallId: "call-child",
			toolName: "child_tool",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 500,
			endTime: Date.now(),
		};

		const parentBlock: ToolBlockType = {
			webchatCallId: "call-parent",
			toolName: "parent_tool",
			status: "done",
			children: new Map([["call-child", childBlock]]),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		render(<ToolBlock {...parentBlock} />);

		expect(screen.getByText("parent_tool")).toBeInTheDocument();
		expect(screen.getByText("child_tool")).toBeInTheDocument();
	});

	it("renders multiple nested children", () => {
		const child1: ToolBlockType = {
			webchatCallId: "call-child-1",
			toolName: "child_tool_1",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 500,
			endTime: Date.now(),
		};

		const child2: ToolBlockType = {
			webchatCallId: "call-child-2",
			toolName: "child_tool_2",
			status: "running",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 300,
		};

		const parentBlock: ToolBlockType = {
			webchatCallId: "call-parent",
			toolName: "parent_tool",
			status: "running",
			children: new Map([
				["call-child-1", child1],
				["call-child-2", child2],
			]),
			timeline: [],
			startTime: Date.now() - 1000,
		};

		render(<ToolBlock {...parentBlock} />);

		expect(screen.getByText("parent_tool")).toBeInTheDocument();
		expect(screen.getByText("child_tool_1")).toBeInTheDocument();
		expect(screen.getByText("child_tool_2")).toBeInTheDocument();
	});

	it("does not render timeline section when timeline is empty", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-7",
			toolName: "tool_no_timeline",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = render(<ToolBlock {...toolBlock} />);

		expect(
			container.querySelector(".runtime-tool-preview"),
		).not.toBeInTheDocument();
	});

	it("does not render children section when no children", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-8",
			toolName: "tool_no_children",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = render(<ToolBlock {...toolBlock} />);

		expect(
			container.querySelector(".runtime-tool-children"),
		).not.toBeInTheDocument();
	});
});
