import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KeybindingHandler } from "./KeybindingManager";
import { KeybindingManager } from "./KeybindingManager";

describe("KeybindingManager", () => {
	let manager: KeybindingManager;
	let handler: KeybindingHandler;

	beforeEach(() => {
		manager = new KeybindingManager();
		handler = vi.fn();
	});

	afterEach(() => {
		manager.stopListening();
	});

	describe("register", () => {
		it("应该注册单个快捷键", () => {
			manager.register("Escape", handler);
			expect(manager.getRegisteredKeys()).toContain("Escape");
		});

		it("应该注册组合快捷键", () => {
			manager.register("Ctrl+N", handler);
			manager.register("Ctrl+Shift+K", handler);
			const keys = manager.getRegisteredKeys();
			expect(keys).toContain("Ctrl+N");
			expect(keys).toContain("Ctrl+Shift+K");
		});

		it("应该允许覆盖已有绑定", () => {
			const handler1 = vi.fn();
			const handler2 = vi.fn();
			manager.register("Ctrl+N", handler1);
			manager.register("Ctrl+N", handler2);
			expect(manager.getRegisteredKeys()).toHaveLength(1);
		});
	});

	describe("unregister", () => {
		it("应该注销指定快捷键", () => {
			manager.register("Ctrl+N", handler);
			manager.unregister("Ctrl+N");
			expect(manager.getRegisteredKeys()).not.toContain("Ctrl+N");
		});
	});

	describe("clear", () => {
		it("应该清空所有绑定", () => {
			manager.register("Ctrl+N", handler);
			manager.register("Ctrl+K", handler);
			manager.clear();
			expect(manager.getRegisteredKeys()).toHaveLength(0);
		});
	});

	describe("handleKeyDown", () => {
		beforeEach(() => {
			manager.register("Ctrl+N", handler);
			manager.startListening();
		});

		it("应该在按下注册的快捷键时触发回调", () => {
			const event = new KeyboardEvent("keydown", {
				key: "n",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).toHaveBeenCalledTimes(1);
		});

		it("应该忽略未注册的快捷键", () => {
			const event = new KeyboardEvent("keydown", {
				key: "m",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).not.toHaveBeenCalled();
		});

		it("应该处理 Escape 键", () => {
			const escHandler = vi.fn();
			manager.register("Escape", escHandler);
			const event = new KeyboardEvent("keydown", {
				key: "Escape",
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(escHandler).toHaveBeenCalledTimes(1);
		});

		it("应该处理组合键 Ctrl+Alt+Shift", () => {
			const comboHandler = vi.fn();
			manager.register("Ctrl+Alt+Shift+K", comboHandler);
			const event = new KeyboardEvent("keydown", {
				key: "k",
				ctrlKey: true,
				altKey: true,
				shiftKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(comboHandler).toHaveBeenCalledTimes(1);
		});

		it("应该忽略输入框内的快捷键（除了 Escape）", () => {
			const input = document.createElement("input");
			document.body.appendChild(input);

			const event = new KeyboardEvent("keydown", {
				key: "n",
				ctrlKey: true,
				bubbles: true,
			});
			Object.defineProperty(event, "target", {
				value: input,
				writable: false,
			});
			window.dispatchEvent(event);
			expect(handler).not.toHaveBeenCalled();

			document.body.removeChild(input);
		});

		it("应该在输入框内也能触发 Escape", () => {
			const escHandler = vi.fn();
			manager.register("Escape", escHandler);

			const input = document.createElement("input");
			document.body.appendChild(input);

			const event = new KeyboardEvent("keydown", {
				key: "Escape",
				bubbles: true,
			});
			Object.defineProperty(event, "target", {
				value: input,
				writable: false,
			});
			window.dispatchEvent(event);
			expect(escHandler).toHaveBeenCalledTimes(1);

			document.body.removeChild(input);
		});
	});

	describe("startListening / stopListening", () => {
		it("应该开始和停止监听", () => {
			manager.register("Ctrl+N", handler);
			manager.startListening();

			let event = new KeyboardEvent("keydown", {
				key: "n",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).toHaveBeenCalledTimes(1);

			manager.stopListening();

			event = new KeyboardEvent("keydown", {
				key: "n",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			// 应该还是只调用一次（停止监听后不再触发）
			expect(handler).toHaveBeenCalledTimes(1);
		});

		it("应该防止重复监听", () => {
			manager.startListening();
			manager.startListening();
			// 不应该抛出错误，且只注册一次监听器
		});
	});

	describe("normalizeKey", () => {
		it("应该标准化 Ctrl+字母", () => {
			manager.register("Ctrl+N", handler);
			manager.startListening();

			const event = new KeyboardEvent("keydown", {
				key: "N",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).toHaveBeenCalled();
		});

		it("应该标准化小写字母为大写", () => {
			manager.register("Ctrl+K", handler);
			manager.startListening();

			const event = new KeyboardEvent("keydown", {
				key: "k",
				ctrlKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).toHaveBeenCalled();
		});

		it("应该将 metaKey（Cmd）映射为 Ctrl", () => {
			manager.register("Ctrl+N", handler);
			manager.startListening();

			const event = new KeyboardEvent("keydown", {
				key: "n",
				metaKey: true,
				bubbles: true,
			});
			window.dispatchEvent(event);
			expect(handler).toHaveBeenCalled();
		});
	});
});
