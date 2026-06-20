import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import { AttachmentImageProvider } from "../rendering/AttachmentImageContext";
import type {
	Attachment,
	AttachmentPreviewResult,
} from "../runtime-client/types";
import { renderWithProviders } from "../test-utils";
import { ToolBlock } from "./ToolBlock";

/** 在固定 zh-CN i18n 上下文中渲染（ToolBlock 内部使用 useTranslation）。 */
function renderToolBlock(ui: ReactElement) {
	return renderWithProviders(ui);
}

function imagePreviewResult(): AttachmentPreviewResult {
	return {
		status: 200,
		ok: true,
		mediaType: "image/png",
		bytes: [137, 80, 78, 71],
		body: null,
	};
}

function renderToolBlockWithAttachmentProvider(ui: ReactElement) {
	const previewAttachment = vi.fn(async () => imagePreviewResult());
	return {
		previewAttachment,
		...renderWithProviders(
			<AttachmentImageProvider client={{ previewAttachment }}>
				{ui}
			</AttachmentImageProvider>,
		),
	};
}

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

		renderToolBlock(<ToolBlock {...toolBlock} />);

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

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

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

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("失败")).toBeInTheDocument();
		const details = container.querySelector(".runtime-tool-block");
		expect(details).toHaveClass("error");
	});

	it("displays cancelled status with correct styling", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-cancelled",
			toolName: "cancelled_tool",
			status: "cancelled",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 2000,
			endTime: Date.now(),
		};

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("已取消")).toBeInTheDocument();
		const details = container.querySelector(".runtime-tool-block");
		expect(details).toHaveClass("cancelled");
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

		renderToolBlock(<ToolBlock {...toolBlock} />);

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

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

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

		renderToolBlock(<ToolBlock {...toolBlock} />);

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

		renderToolBlock(<ToolBlock {...parentBlock} />);

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

		renderToolBlock(<ToolBlock {...parentBlock} />);

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

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

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

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(
			container.querySelector(".runtime-tool-children"),
		).not.toBeInTheDocument();
	});

	it("结构化渲染可解析为 JSON 的工具结果", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-json",
			toolName: "json_tool",
			status: "done",
			resultPreview: '{"name":"小明","age":18}',
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		// 结构化展示：对齐 WebUI 的 runtime-tool-structured-* 类名
		expect(
			container.querySelector(".runtime-tool-structured-list"),
		).toBeTruthy();
		expect(screen.getByText("name")).toBeInTheDocument();
		expect(screen.getByText("小明")).toBeInTheDocument();
		expect(screen.getByText("age")).toBeInTheDocument();
	});

	it("兼容 Python 风格工具预览并按 WebUI 结构化类名渲染", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-pythonish",
			toolName: "pythonish_tool",
			status: "done",
			resultPreview: "{'ok': True, 'items': [None, 'done']}",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(
			container.querySelector(".runtime-tool-structured-list"),
		).toBeTruthy();
		expect(screen.getByText("ok")).toBeInTheDocument();
		expect(screen.getByText("true")).toHaveClass("boolean");
		expect(screen.getByText("null")).toHaveClass("muted");
	});

	it("非结构化工具输出按 Markdown 渲染", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-markdown",
			toolName: "markdown_tool",
			status: "done",
			resultPreview: "**加粗结果**",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(screen.getByText("加粗结果").closest("strong")).toBeInTheDocument();
	});

	it("工具输出附件标签复用 MarkdownContent 图片预览链路", async () => {
		const imageAttachment: Attachment = {
			id: "pic_tool",
			name: "tool.png",
			size: 2048,
			mediaType: "image/png",
			kind: "image",
			downloadUrl: null,
			previewUrl: null,
			discarded: false,
		};
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-image",
			toolName: "image_tool",
			status: "done",
			resultPreview: '结果<attachment uid="pic_tool"/>',
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { previewAttachment } = renderToolBlockWithAttachmentProvider(
			<ToolBlock {...toolBlock} attachments={[imageAttachment]} />,
		);

		expect(await screen.findByAltText("tool.png")).toBeInTheDocument();
		expect(previewAttachment).toHaveBeenCalledWith({
			attachmentId: "pic_tool",
		});
	});

	it("未知 pic_ 附件标签按 WebUI 规则 fallback 为图片预览", async () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-pic-fallback",
			toolName: "image_tool",
			status: "done",
			resultPreview: '<attachment uid="pic_missing"/>',
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { previewAttachment } = renderToolBlockWithAttachmentProvider(
			<ToolBlock {...toolBlock} />,
		);

		expect(await screen.findByRole("img")).toBeInTheDocument();
		expect(previewAttachment).toHaveBeenCalledWith({
			attachmentId: "pic_missing",
		});
	});

	it("非 JSON 的工具结果回退为普通预览文本", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-text",
			toolName: "text_tool",
			status: "done",
			resultPreview: "这是一段纯文本结果",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 1000,
			endTime: Date.now(),
		};

		const { container } = renderToolBlock(<ToolBlock {...toolBlock} />);

		expect(container.querySelector(".runtime-tool-structured-list")).toBeNull();
		expect(screen.getByText("这是一段纯文本结果")).toBeInTheDocument();
	});

	it("agent 运行中在阶段标签后展示 stageDetail", () => {
		const toolBlock: ToolBlockType = {
			webchatCallId: "call-agent",
			toolName: "web_agent",
			status: "running",
			isAgent: true,
			currentStage: "waiting_model",
			stageDetail: "Claude Opus 4.8",
			children: new Map(),
			timeline: [],
			startTime: Date.now() - 500,
		};

		renderToolBlock(<ToolBlock {...toolBlock} />);

		// "等待模型 · Claude Opus 4.8"（zh-CN 阶段标签 + detail）
		expect(screen.getByText(/Claude Opus 4\.8/)).toBeInTheDocument();
		expect(screen.getByText(/等待模型/)).toBeInTheDocument();
	});
});
