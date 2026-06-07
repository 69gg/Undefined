import { useState } from "react";
import {
	type ConnectionState,
	type RuntimeHealth,
	type SecretStatus,
	probeRuntime,
	probeSecretStorage,
} from "./runtime";

const defaultRuntimeUrl = "http://127.0.0.1:8788";

function statusLabel(state: ConnectionState): string {
	const labels: Record<ConnectionState, string> = {
		idle: "待连接",
		connecting: "正在连接",
		connected: "已连接",
		streaming: "正在接收事件",
		resuming: "正在续接",
		json_fallback: "已降级查询",
		disconnected: "连接断开",
	};
	return labels[state];
}

export function App() {
	const [runtimeUrl, setRuntimeUrl] = useState(defaultRuntimeUrl);
	const [connectionState, setConnectionState] =
		useState<ConnectionState>("idle");
	const [secretStatus, setSecretStatus] = useState<SecretStatus | null>(null);
	const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(
		null,
	);
	const [error, setError] = useState("");

	async function runSecretProbe(): Promise<void> {
		setError("");
		try {
			const result = await probeSecretStorage();
			setSecretStatus(result);
		} catch (err) {
			setError(String(err));
		}
	}

	async function runRuntimeProbe(): Promise<void> {
		setError("");
		setRuntimeHealth(null);
		setConnectionState("connecting");
		try {
			const result = await probeRuntime(runtimeUrl);
			setRuntimeHealth(result);
			setConnectionState(result.ok ? "connected" : "disconnected");
		} catch (err) {
			setRuntimeHealth(null);
			setConnectionState("disconnected");
			setError(String(err));
		}
	}

	return (
		<main className="app-shell">
			<section className="hero">
				<p className="eyebrow">Undefined Chat PoC</p>
				<h1>原生优先 WebChat 客户端验证</h1>
				<p>当前 PoC 只验证连接、安全存储、事件流、上传和 HTML 预览关键路径。</p>
			</section>
			<section className="panel">
				<label htmlFor="runtime-url">Runtime URL</label>
				<div className="row">
					<input
						id="runtime-url"
						value={runtimeUrl}
						onChange={(event) => setRuntimeUrl(event.currentTarget.value)}
					/>
					<button type="button" onClick={runRuntimeProbe}>
						测试连接
					</button>
				</div>
				<div className={`status status-${connectionState}`}>
					{statusLabel(connectionState)}
				</div>
				{runtimeHealth ? (
					<pre>{JSON.stringify(runtimeHealth, null, 2)}</pre>
				) : null}
			</section>
			<section className="panel">
				<div className="row">
					<strong>Secret Storage</strong>
					<button type="button" onClick={runSecretProbe}>
						探测
					</button>
				</div>
				{secretStatus ? (
					<pre>{JSON.stringify(secretStatus, null, 2)}</pre>
				) : (
					<p>尚未探测 Stronghold/keyring 状态。</p>
				)}
			</section>
			{error ? <section className="error">{error}</section> : null}
		</main>
	);
}
