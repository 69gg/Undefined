import { invoke } from "@tauri-apps/api/core";
import { appDataDir, join } from "@tauri-apps/api/path";
import { type Client, Stronghold } from "@tauri-apps/plugin-stronghold";

const CLIENT_NAME = "undefined-chat";
const API_KEY_RECORD = "runtime-api-key";

async function loadClient(): Promise<{
	stronghold: Stronghold;
	client: Client;
}> {
	// PoC-only trusted renderer boundary: production should move API key
	// save/load into Rust commands so the renderer never sees this vault password.
	const vaultPassword = await invoke<string>("ensure_vault_password");
	const vaultPath = await join(await appDataDir(), "undefined-chat.vault.hold");
	const stronghold = await Stronghold.load(vaultPath, vaultPassword);
	try {
		return { stronghold, client: await stronghold.loadClient(CLIENT_NAME) };
	} catch {
		return { stronghold, client: await stronghold.createClient(CLIENT_NAME) };
	}
}

export async function saveRuntimeApiKey(apiKey: string): Promise<void> {
	const { stronghold, client } = await loadClient();
	const store = client.getStore();
	const data = Array.from(new TextEncoder().encode(apiKey));
	await store.insert(API_KEY_RECORD, data);
	await stronghold.save();
}

export async function loadRuntimeApiKey(): Promise<string | null> {
	const { client } = await loadClient();
	const store = client.getStore();
	const data = await store.get(API_KEY_RECORD);
	if (!data) {
		return null;
	}
	return new TextDecoder().decode(new Uint8Array(data));
}
