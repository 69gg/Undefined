import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { renderWithProviders } from "../test-utils";
import { ImagePreview } from "./ImagePreview";
import { MessageTimelineContent } from "./MessageTimelineContent";

function renderTimeline() {
	renderWithProviders(
		<>
			<button type="button">预览前</button>
			<MessageTimelineContent
				timeline={[
					{
						type: "message",
						content: "![测试图片](https://example.com/image.png)",
					},
				]}
				onPreviewHtml={vi.fn()}
			/>
			<button type="button">预览后</button>
		</>,
	);
	return screen.getByRole("button", { name: "测试图片" });
}

describe("ImagePreview keyboard interaction", () => {
	test.each(["{Enter}", " "])(
		"opens from the image with %s and moves focus into the dialog",
		async (key) => {
			const user = userEvent.setup();
			const trigger = renderTimeline();
			await user.tab();
			await user.tab();
			expect(trigger).toHaveFocus();

			await user.keyboard(key);

			const dialog = screen.getByRole("dialog", { name: "测试图片" });
			expect(dialog).toHaveAttribute("aria-modal", "true");
			expect(
				within(dialog).getByRole("button", { name: "关闭图片预览" }),
			).toHaveFocus();
		},
	);

	test("keeps Tab and Shift+Tab inside the dialog, including after clicking the image", async () => {
		const user = userEvent.setup();
		const trigger = renderTimeline();
		await user.click(trigger);
		const dialog = screen.getByRole("dialog");
		const close = within(dialog).getByRole("button", { name: "关闭图片预览" });

		await user.tab();
		expect(close).toHaveFocus();
		await user.tab({ shift: true });
		expect(close).toHaveFocus();
		await user.click(within(dialog).getByRole("img"));
		expect(dialog).toBeInTheDocument();
		await user.tab();
		expect(close).toHaveFocus();
	});

	test.each(["Escape", "backdrop", "close button", "Enter", "Space"])(
		"dismisses via %s and restores focus to the triggering image",
		async (action) => {
			const user = userEvent.setup();
			const trigger = renderTimeline();
			await user.click(trigger);
			const dialog = screen.getByRole("dialog");
			const close = within(dialog).getByRole("button", {
				name: "关闭图片预览",
			});

			if (action === "backdrop") {
				await user.click(dialog);
			} else if (action === "close button") {
				await user.click(close);
			} else if (action === "Escape") {
				await user.click(within(dialog).getByRole("img"));
				await user.keyboard("{Escape}");
			} else {
				await user.keyboard(action === "Enter" ? "{Enter}" : " ");
			}

			expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
			expect(trigger).toHaveFocus();
			await user.tab();
			expect(screen.getByRole("button", { name: "预览后" })).toHaveFocus();
		},
	);

	test("calls onClose only once for a close-button click", async () => {
		const user = userEvent.setup();
		const onClose = vi.fn();
		renderWithProviders(
			<ImagePreview src="/image.png" alt="测试图片" open onClose={onClose} />,
		);

		await user.click(screen.getByRole("button", { name: "关闭图片预览" }));

		expect(onClose).toHaveBeenCalledTimes(1);
	});

	test("keeps focus when onClose changes and uses the latest callback", async () => {
		const user = userEvent.setup();
		const previousClose = vi.fn();
		const nextClose = vi.fn();
		const { rerender } = renderWithProviders(
			<ImagePreview
				src="/image.png"
				alt="测试图片"
				open
				onClose={previousClose}
			/>,
		);

		rerender(
			<ImagePreview src="/image.png" alt="测试图片" open onClose={nextClose} />,
		);

		expect(screen.getByRole("button", { name: "关闭图片预览" })).toHaveFocus();
		await user.keyboard("{Escape}");
		expect(previousClose).not.toHaveBeenCalled();
		expect(nextClose).toHaveBeenCalledTimes(1);
	});
});
