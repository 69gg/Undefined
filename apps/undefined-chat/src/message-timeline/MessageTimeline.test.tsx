import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { event, historyItem, job } from "../test-fixtures";
import { MessageTimeline } from "./MessageTimeline";

describe("MessageTimeline", () => {
	test("renders text, code, attachments, references, tool and agent timeline entries, job status, and errors", async () => {
		const onPreviewHtml = vi.fn();
		const activeJob = job({
			jobId: "job-1",
			currentStage: "tool_call",
			currentStageDetail: "正在调用工具",
			currentToolCalls: [
				{
					id: "call-1",
					name: "group.get_member_info",
					status: "running",
					elapsedMs: 800,
				},
			],
			currentAgentStages: [
				{
					id: "agent-1",
					name: "planner",
					stage: "thinking",
					status: "running",
					elapsedMs: 600,
				},
			],
		});

		render(
			<MessageTimeline
				activeJob={activeJob}
				connectionState="streaming"
				events={[
					event({
						seq: 2,
						event: "tool_result",
						payload: {
							name: "group.get_member_info",
							result_preview: "昵称：小明",
						},
					}),
					event({
						seq: 3,
						event: "agent_stage",
						payload: {
							agent_name: "planner",
							stage: "thinking",
							detail: "拆解任务",
						},
					}),
					event({
						seq: 4,
						event: "error",
						payload: { error: "工具调用失败" },
					}),
				]}
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
								downloadUrl: "/download/report.png",
								previewUrl: "/preview/report.png",
								discarded: false,
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

		expect(screen.getByText("参考这条消息")).toBeTruthy();
		expect(screen.getByText("report.png")).toBeTruthy();
		expect(screen.getByText(/引用/)).toBeTruthy();
		expect(screen.getByText("group.get_member_info")).toBeTruthy();
		expect(screen.getByText("planner")).toBeTruthy();
		expect(screen.getByText("正在调用工具")).toBeTruthy();
		expect(screen.getByText("工具调用失败")).toBeTruthy();
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
				events={[]}
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
