import { screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, test, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import {
	hasRenderableTimeline,
	MessageTimelineContent,
} from "./MessageTimelineContent";

/** MessageTimelineContent 内部经 ToolBlock 使用 useTranslation，需 LanguageProvider。 */
function renderContent(ui: ReactElement) {
	return renderWithProviders(ui);
}

describe("hasRenderableTimeline", () => {
	test("returns false for empty or undefined timeline", () => {
		expect(hasRenderableTimeline(undefined)).toBe(false);
		expect(hasRenderableTimeline([])).toBe(false);
	});

	test("returns false when timeline has only blank message entries", () => {
		expect(hasRenderableTimeline([{ type: "message", content: "   " }])).toBe(
			false,
		);
	});

	test("returns true when timeline contains a tool call", () => {
		expect(
			hasRenderableTimeline([
				{ type: "call", call: { name: "search", status: "done" } },
			]),
		).toBe(true);
	});

	test("returns true when timeline contains a non-empty message", () => {
		expect(hasRenderableTimeline([{ type: "message", content: "hello" }])).toBe(
			true,
		);
	});
});

describe("MessageTimelineContent", () => {
	test("keeps historical Agent messages and nested calls inside the Agent in order", () => {
		renderContent(
			<MessageTimelineContent
				onPreviewHtml={vi.fn()}
				fallbackContent="Before After Final"
				timeline={[
					{
						type: "call",
						call: {
							id: "agent",
							name: "research",
							is_agent: true,
							status: "done",
							timeline: [
								{ type: "message", content: "Before" },
								{
									type: "call",
									call: { id: "nested", name: "search", status: "done" },
								},
								{ type: "message", content: "After" },
							],
						},
					},
					{ type: "message", content: "Final" },
				]}
			/>,
		);
		const agent = screen.getByText("research").closest("details");
		expect(agent?.contains(screen.getByText("Before"))).toBe(true);
		expect(agent?.contains(screen.getByText("After"))).toBe(true);
		expect(agent?.contains(screen.getByText("Final"))).toBe(false);
		expect(screen.getAllByText("Before")).toHaveLength(1);
		expect(
			screen
				.getByText("Before")
				.compareDocumentPosition(screen.getByText("search")) &
				Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
		expect(
			screen
				.getByText("search")
				.compareDocumentPosition(screen.getByText("After")) &
				Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
	});

	test("renders message text and tool calls in order without duplicating content", () => {
		renderContent(
			<MessageTimelineContent
				timeline={[
					{ type: "message", seq: 1, content: "第一段回答内容" },
					{
						type: "call",
						seq: 2,
						call: {
							name: "send_message",
							status: "done",
							duration_ms: 2,
							arguments_preview: '{"text":"hi"}',
							result_preview: "ok",
						},
					},
					{ type: "message", seq: 3, content: "第二段补充内容" },
				]}
				fallbackContent={"第一段回答内容\n\n第二段补充内容"}
				onPreviewHtml={vi.fn()}
			/>,
		);

		// 两段文本各渲染一次，不因 fallbackContent 而重复
		expect(screen.getAllByText("第一段回答内容")).toHaveLength(1);
		expect(screen.getAllByText("第二段补充内容")).toHaveLength(1);
		expect(screen.getByText("send_message")).toBeTruthy();
		expect(screen.getByText("完成")).toBeTruthy();
	});

	test("falls back to full-text content when timeline has no message entries", () => {
		renderContent(
			<MessageTimelineContent
				timeline={[
					{
						type: "call",
						seq: 1,
						call: { name: "web_agent", is_agent: true, status: "done" },
					},
				]}
				fallbackContent="这是完整正文兜底"
				onPreviewHtml={vi.fn()}
			/>,
		);

		expect(screen.getByText("这是完整正文兜底")).toBeTruthy();
		expect(screen.getByText("Agent")).toBeTruthy();
	});

	test("renders nested child calls inside a tool block", () => {
		renderContent(
			<MessageTimelineContent
				timeline={[
					{
						type: "call",
						seq: 1,
						call: {
							name: "web_agent",
							is_agent: true,
							status: "done",
							timeline: [
								{
									type: "call",
									seq: 2,
									call: { name: "search", status: "done" },
								},
							],
						},
					},
				]}
				onPreviewHtml={vi.fn()}
			/>,
		);

		expect(screen.getByText("Agent")).toBeTruthy();
		expect(screen.getByText("search")).toBeTruthy();
	});
});
