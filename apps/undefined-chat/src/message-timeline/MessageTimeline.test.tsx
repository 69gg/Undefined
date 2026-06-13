import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { historyItem, job } from "../test-fixtures";
import { MessageTimeline } from "./MessageTimeline";

describe("MessageTimeline", () => {
	test("renders text, code, attachments, references, and streaming bot message with tool calls", async () => {
		const onPreviewHtml = vi.fn();
		const activeJob = job({
			jobId: "job-1",
			reply: "正在处理您的请求...",
			currentStage: "tool_call",
			currentStageDetail: "正在调用工具",
			currentToolCalls: [
				{
					id: "call-1",
					name: "group.get_member_info",
					status: "running",
					elapsedMs: 800,
					argumentsPreview: '{"user_id": "12345"}',
					resultPreview: "昵称：小明",
				},
			],
			currentAgentStages: [],
		});

		render(
			<MessageTimeline
				activeJob={activeJob}
				connectionState="streaming"
				items={[
					historyItem({
						messageId: "u-1",
						role: "user",
						content: "参考这条消息",
					}),
					historyItem({
						messageId: "b-1",
						role: "bot",
						content:
							'这里有代码：\n```html\n<div class="preview"><h1>报告</h1><script>alert(1)</script></div>\n```',
						attachments: [
							{
								id: "att-1",
								name: "report.png",
								size: 2048,
								mediaType: "image/png",
								kind: "image",
								discarded: false,
								downloadUrl: "/download/report.png",
								previewUrl: "/preview/report.png",
							},
						],
						references: [
							{
								messageId: "u-1",
								quote: "参考这条消息",
							},
						],
					}),
				]}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={onPreviewHtml}
				onSaveAttachment={vi.fn()}
			/>,
		);

		// 历史消息内容
		expect(screen.getByText("参考这条消息")).toBeTruthy();
		expect(screen.getByAltText("report.png")).toBeTruthy();
		expect(screen.getByText(/引用/)).toBeTruthy();

		// 流式 bot 消息
		expect(screen.getByTestId("streaming-message")).toBeTruthy();
		expect(screen.getByText("正在处理您的请求...")).toBeTruthy();
		expect(screen.getByText("group.get_member_info")).toBeTruthy();

		// HTML 预览不在流式消息中渲染
		expect(screen.queryByRole("heading", { name: "报告" })).toBeNull();

		await userEvent.click(screen.getByRole("button", { name: "预览 HTML" }));

		expect(onPreviewHtml).toHaveBeenCalledWith({
			title: "HTML 预览",
			html: '<div class="preview"><h1>报告</h1><script>alert(1)</script></div>',
		});
	});

	test("uses windowed rendering for large histories", () => {
		const manyItems = Array.from({ length: 180 }, (_, index) =>
			historyItem({
				messageId: `msg-${index}`,
				content: `消息 ${index}`,
				timestamp: `2026-06-08T10:${String(index).padStart(2, "0")}:00`,
			}),
		);

		render(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				items={manyItems}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
			/>,
		);

		const timeline = screen.getByRole("log", { name: "消息" });
		expect(within(timeline).queryByText("消息 0")).toBeNull();
		expect(within(timeline).getByText("消息 179")).toBeTruthy();
		expect(within(timeline).getAllByTestId("message-row").length).toBeLessThan(
			80,
		);
	});
});
