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

export type StartJobEventStreamInput = {
	runtimeUrl: string;
	apiKey: string;
	jobId: string;
	afterSeq: number;
};

export type UploadAttachmentInput = {
	runtimeUrl: string;
	apiKey: string;
	filePath: string;
};

export type UploadAttachmentResult = {
	status: number;
	body: string;
};

export async function probeSecretStorage(): Promise<SecretStatus> {
	return await invoke<SecretStatus>("probe_secret_storage");
}

export async function probeRuntime(runtimeUrl: string): Promise<RuntimeHealth> {
	return await invoke<RuntimeHealth>("probe_runtime", { runtimeUrl });
}

export async function startJobEventStream(
	input: StartJobEventStreamInput,
): Promise<void> {
	await invoke("start_job_event_stream", { input });
}

export async function uploadAttachmentStreaming(
	input: UploadAttachmentInput,
): Promise<UploadAttachmentResult> {
	return await invoke<UploadAttachmentResult>("upload_attachment_streaming", {
		input,
	});
}
