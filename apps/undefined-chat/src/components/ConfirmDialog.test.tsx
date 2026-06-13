import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
	test("关闭时不渲染", () => {
		const { container } = render(
			<ConfirmDialog
				open={false}
				title="删除会话"
				message="确定？"
				onConfirm={vi.fn()}
				onCancel={vi.fn()}
			/>,
		);
		expect(container.firstChild).toBeNull();
	});

	test("确认与取消触发对应回调", async () => {
		const onConfirm = vi.fn();
		const onCancel = vi.fn();
		render(
			<ConfirmDialog
				open
				title="删除会话"
				message="确定删除该会话？"
				confirmLabel="删除"
				cancelLabel="取消"
				danger
				onConfirm={onConfirm}
				onCancel={onCancel}
			/>,
		);

		expect(screen.getByText("删除会话")).toBeInTheDocument();
		expect(screen.getByText("确定删除该会话？")).toBeInTheDocument();

		await userEvent.click(screen.getByRole("button", { name: "删除" }));
		expect(onConfirm).toHaveBeenCalledOnce();

		await userEvent.click(screen.getByRole("button", { name: "取消" }));
		expect(onCancel).toHaveBeenCalledOnce();
	});
});
