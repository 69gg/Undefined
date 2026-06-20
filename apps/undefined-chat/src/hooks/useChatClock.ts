import { useEffect, useState } from "react";

/**
 * 默认时钟刷新间隔（毫秒）。对齐 ChatStageLabel / ToolBlock 原有的 500ms 节奏，
 * 让"运行中"用时显示平滑推进而不过度重渲染。
 */
const DEFAULT_INTERVAL_MS = 500;

/**
 * 随时间推进的全局聊天时钟 hook。
 *
 * 用于驱动"运行中"用时（如 `Date.now() - startTime`）的实时刷新，统一替代
 * 各组件内部各自维护的 `setInterval`，消除重复定时器。
 *
 * - `active=true`（默认）：每 `intervalMs` 返回一个新的 `Date.now()` 时间戳触发重渲染。
 * - `active=false`：停止定时器（省资源），仅返回挂载时刻的时间戳，不再推进。
 *
 * @param active 是否启用定时推进；最终状态/历史消息可传 false 停止。
 * @param intervalMs 刷新间隔（毫秒），默认 500ms。
 * @returns 当前时间戳（毫秒），随定时器推进而变化。
 */
export function useChatClock(
	active = true,
	intervalMs: number = DEFAULT_INTERVAL_MS,
): number {
	const [now, setNow] = useState<number>(() => Date.now());

	useEffect(() => {
		if (!active) {
			return;
		}
		// 进入运行态时立即同步一次，避免沿用挂载时的旧时间戳。
		setNow(Date.now());
		const timer = setInterval(() => {
			setNow(Date.now());
		}, intervalMs);
		return () => clearInterval(timer);
	}, [active, intervalMs]);

	return now;
}
