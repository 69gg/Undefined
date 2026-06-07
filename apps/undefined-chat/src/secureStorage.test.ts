import { invoke } from "@tauri-apps/api/core";
import { appDataDir, join } from "@tauri-apps/api/path";
import { Stronghold } from "@tauri-apps/plugin-stronghold";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { loadRuntimeApiKey, saveRuntimeApiKey } from "./secureStorage";

vi.mock("@tauri-apps/api/core", () => ({
	invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/path", () => ({
	appDataDir: vi.fn(),
	join: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-stronghold", () => ({
	Stronghold: {
		load: vi.fn(),
	},
}));

function bytes(value: string): number[] {
	return Array.from(new TextEncoder().encode(value));
}

describe("secureStorage", () => {
	const insert = vi.fn();
	const get = vi.fn();
	const save = vi.fn();
	const loadClient = vi.fn();
	const createClient = vi.fn();
	const store = { insert, get };
	const client = {
		getStore: vi.fn(() => store),
	};
	const stronghold = {
		path: "/app-data/undefined-chat.vault.hold",
		loadClient,
		createClient,
		save,
		unload: vi.fn(),
	};

	beforeEach(() => {
		vi.resetAllMocks();
		vi.mocked(invoke).mockResolvedValue("vault-secret");
		vi.mocked(appDataDir).mockResolvedValue("/app-data");
		vi.mocked(join).mockResolvedValue("/app-data/undefined-chat.vault.hold");
		vi.mocked(Stronghold.load).mockResolvedValue(stronghold);
		loadClient.mockResolvedValue(client);
		createClient.mockResolvedValue(client);
	});

	test("save encodes and inserts the API key then saves stronghold", async () => {
		await saveRuntimeApiKey("api-key");

		expect(invoke).toHaveBeenCalledWith("ensure_vault_password");
		expect(join).toHaveBeenCalledWith("/app-data", "undefined-chat.vault.hold");
		expect(Stronghold.load).toHaveBeenCalledWith(
			"/app-data/undefined-chat.vault.hold",
			"vault-secret",
		);
		expect(insert).toHaveBeenCalledWith("runtime-api-key", bytes("api-key"));
		expect(save).toHaveBeenCalledOnce();
	});

	test("load returns decoded API key", async () => {
		get.mockResolvedValue(new Uint8Array(bytes("api-key")));

		const value = await loadRuntimeApiKey();

		expect(value).toBe("api-key");
		expect(get).toHaveBeenCalledWith("runtime-api-key");
	});

	test("load returns null when API key record is missing", async () => {
		get.mockResolvedValue(null);

		await expect(loadRuntimeApiKey()).resolves.toBeNull();
	});

	test("falls back to creating a client when loading the client fails", async () => {
		loadClient.mockRejectedValue(new Error("missing client"));

		await saveRuntimeApiKey("api-key");

		expect(createClient).toHaveBeenCalledWith("undefined-chat");
		expect(insert).toHaveBeenCalledWith("runtime-api-key", bytes("api-key"));
	});
});
