import { invoke } from "@tauri-apps/api/core";

export type ConnectionState =
	| "idle"
	| "connecting"
	| "connected"
	| "streaming"
	| "resuming"
	| "json_fallback"
	| "disconnected";

export type SecretStatus = {
	available: boolean;
	degraded: boolean;
	detail: string;
};

export type RuntimeHealth = {
	ok: boolean;
	status: number;
	body: string;
};

export async function probeSecretStorage(): Promise<SecretStatus> {
	return await invoke<SecretStatus>("probe_secret_storage");
}

export async function probeRuntime(runtimeUrl: string): Promise<RuntimeHealth> {
	return await invoke<RuntimeHealth>("probe_runtime", { runtimeUrl });
}
