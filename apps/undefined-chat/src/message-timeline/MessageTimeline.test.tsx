import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AttachmentImageProvider } from "../rendering/AttachmentImageContext";
import { historyItem, job } from "../test-fixtures";
import { MessageTimeline } from "./MessageTimeline";

function renderTimeline(ui: ReactNode) {
	const previewAttachment = vi.fn(async () => ({
		status: 200,
		ok: true,
		mediaType: "image/png",
		bytes: [137, 80, 78, 71],
		body: null,
	}));
	return render(
		<AttachmentImageProvider client={{ previewAttachment }}>
			{ui}
		</AttachmentImageProvider>,
	);
}

describe("MessageTimeline", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

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

		renderTimeline(
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

		// 历史消息内容（user 正文 + bot 引用块均含该文本）
		expect(screen.getAllByText("参考这条消息").length).toBeGreaterThanOrEqual(
			1,
		);
		// 附件图片经 blob 异步加载后渲染
		expect(await screen.findByAltText("report.png")).toBeTruthy();
		// 引用块（runtime-quote-block，对齐 WebUI 结构）
		const quoteBlock = document.querySelector(".runtime-quote-block");
		expect(quoteBlock).toBeTruthy();
		expect(quoteBlock?.textContent).toContain("参考这条消息");

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

		renderTimeline(
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

	test("renders load-more control and invokes history pagination", async () => {
		const onLoadMoreHistory = vi.fn(async () => undefined);
		renderTimeline(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				hasMoreHistory
				items={[
					historyItem({ messageId: "msg-1", content: "已加载消息 1" }),
					historyItem({ messageId: "msg-2", content: "已加载消息 2" }),
				]}
				onLoadMoreHistory={onLoadMoreHistory}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
			/>,
		);

		await userEvent.click(screen.getByRole("button", { name: "加载更早消息" }));

		expect(onLoadMoreHistory).toHaveBeenCalledOnce();
	});

	test("keeps scroll position anchored after loading older history", async () => {
		const rafCallbacks: FrameRequestCallback[] = [];
		vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
			rafCallbacks.push(callback);
			return rafCallbacks.length;
		});
		const onLoadMoreHistory = vi.fn(async () => undefined);
		renderTimeline(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				hasMoreHistory
				items={[
					historyItem({ messageId: "msg-1", content: "已加载消息 1" }),
					historyItem({ messageId: "msg-2", content: "已加载消息 2" }),
				]}
				onLoadMoreHistory={onLoadMoreHistory}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
			/>,
		);

		const timeline = screen.getByRole("log", { name: "消息" });
		Object.defineProperty(timeline, "scrollHeight", {
			configurable: true,
			value: 1000,
		});
		Object.defineProperty(timeline, "clientHeight", {
			configurable: true,
			value: 400,
		});
		timeline.scrollTop = 20;

		await userEvent.click(screen.getByRole("button", { name: "加载更早消息" }));

		Object.defineProperty(timeline, "scrollHeight", {
			configurable: true,
			value: 1400,
		});
		await Promise.resolve();
		for (const callback of rafCallbacks.splice(0)) {
			callback(0);
		}

		expect(timeline.scrollTop).toBe(420);
		expect(onLoadMoreHistory).toHaveBeenCalledOnce();
	});

	test("点击附件图片以已加载的 blob URL 打开查看器", async () => {
		const onOpenImage = vi.fn();
		renderTimeline(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				items={[
					historyItem({
						messageId: "b-img",
						role: "bot",
						content: "看图",
						attachments: [
							{
								id: "img-1",
								name: "chart.png",
								size: 2048,
								mediaType: "image/png",
								kind: "image",
								downloadUrl: "/api/v1/chat/attachments/img-1",
								previewUrl: "/api/v1/chat/attachments/img-1/preview",
								discarded: false,
							},
						],
					}),
				]}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
				onOpenImage={onOpenImage}
			/>,
		);

		await userEvent.click(await screen.findByAltText("chart.png"));

		expect(onOpenImage).toHaveBeenCalledWith(
			expect.stringMatching(/^blob:/),
			"chart.png",
		);
	});

	test("正文 <attachment uid/> 引用的图片只内联渲染，不在附件区重复", async () => {
		renderTimeline(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				items={[
					historyItem({
						messageId: "b-inline",
						role: "bot",
						content: '看图<attachment uid="img-1"/>',
						attachments: [
							{
								id: "img-1",
								name: "chart.png",
								size: 2048,
								mediaType: "image/png",
								kind: "image",
								downloadUrl: "/api/v1/chat/attachments/img-1",
								previewUrl: "/api/v1/chat/attachments/img-1/preview",
								discarded: false,
							},
						],
					}),
				]}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
			/>,
		);

		// 正文已内联该图，附件区被过滤，全局只应有一个对应图片
		const imgs = await screen.findAllByAltText("chart.png");
		expect(imgs).toHaveLength(1);
	});

	test("未被正文引用的图片（如上传）仍在附件区展示", async () => {
		renderTimeline(
			<MessageTimeline
				activeJob={null}
				connectionState="connected"
				items={[
					historyItem({
						messageId: "u-upload",
						role: "user",
						content: "看我的图",
						attachments: [
							{
								id: "img-2",
								name: "photo.png",
								size: 2048,
								mediaType: "image/png",
								kind: "image",
								downloadUrl: "/api/v1/chat/attachments/img-2",
								previewUrl: "/api/v1/chat/attachments/img-2/preview",
								discarded: false,
							},
						],
					}),
				]}
				onPreviewAttachment={vi.fn()}
				onPreviewHtml={vi.fn()}
				onSaveAttachment={vi.fn()}
			/>,
		);

		// content 未引用该 uid，附件区保留展示
		const imgs = await screen.findAllByAltText("photo.png");
		expect(imgs).toHaveLength(1);
	});
});
