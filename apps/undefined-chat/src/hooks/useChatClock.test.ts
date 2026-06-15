import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useChatClock } from "./useChatClock";

describe("useChatClock", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	test("active 时随定时器推进时间戳", () => {
		const { result } = renderHook(() => useChatClock(true, 500));
		const initial = result.current;
		act(() => {
			vi.advanceTimersByTime(500);
		});
		expect(result.current).toBeGreaterThanOrEqual(initial);
		const afterFirst = result.current;
		act(() => {
			vi.advanceTimersByTime(500);
		});
		expect(result.current).toBeGreaterThanOrEqual(afterFirst);
	});

	test("inactive 时不启动定时器（时间戳不再推进）", () => {
		const { result } = renderHook(() => useChatClock(false, 500));
		const initial = result.current;
		act(() => {
			vi.advanceTimersByTime(2000);
		});
		expect(result.current).toBe(initial);
	});

	test("从 inactive 切到 active 时立即同步一次", () => {
		const nowSpy = vi.spyOn(Date, "now");
		nowSpy.mockReturnValue(1000);
		const { result, rerender } = renderHook(
			({ active }: { active: boolean }) => useChatClock(active, 500),
			{ initialProps: { active: false } },
		);
		expect(result.current).toBe(1000);
		nowSpy.mockReturnValue(5000);
		act(() => {
			rerender({ active: true });
		});
		// 进入 active 时 effect 立即 setNow(Date.now())
		expect(result.current).toBe(5000);
		nowSpy.mockRestore();
	});
});
