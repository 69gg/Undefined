import { type FormEvent, useEffect, useState } from "react";

export type RuntimeConfig = {
	runtimeUrl: string;
	usedAt: number;
};

export type ConnectionSetupProps = {
	currentUrl?: string;
	onConnect: (url: string, apiKey: string) => void;
};

/**
 * Android 连接配置组件
 * - 配置 Runtime URL 和 API Key
 * - 显示历史配置（最近使用）
 * - 本地存储配置历史
 */
export function ConnectionSetup({
	currentUrl,
	onConnect,
}: ConnectionSetupProps) {
	const [url, setUrl] = useState(currentUrl ?? "http://192.168.1.100:8788");
	const [apiKey, setApiKey] = useState("");
	const [savedConfigs, setSavedConfigs] = useState<RuntimeConfig[]>([]);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		loadSavedConfigs().then(setSavedConfigs);
	}, []);

	async function loadSavedConfigs(): Promise<RuntimeConfig[]> {
		try {
			const stored = localStorage.getItem("undefined-runtime-history");
			if (!stored) {
				return [];
			}
			const parsed = JSON.parse(stored) as RuntimeConfig[];
			return parsed.sort((a, b) => b.usedAt - a.usedAt).slice(0, 5);
		} catch {
			return [];
		}
	}

	async function saveConfigToHistory(runtimeUrl: string): Promise<void> {
		const configs = await loadSavedConfigs();
		const updated = [
			{ runtimeUrl, usedAt: Date.now() },
			...configs.filter((item) => item.runtimeUrl !== runtimeUrl),
		].slice(0, 5);
		localStorage.setItem("undefined-runtime-history", JSON.stringify(updated));
	}

	function handleConnect(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setError(null);

		const trimmedUrl = url.trim();
		const trimmedKey = apiKey.trim();

		if (!trimmedUrl) {
			setError("请输入 Runtime URL");
			return;
		}
		if (!trimmedKey) {
			setError("请输入 API Key");
			return;
		}

		try {
			new URL(trimmedUrl);
		} catch {
			setError("URL 格式不正确");
			return;
		}

		void saveConfigToHistory(trimmedUrl);
		onConnect(trimmedUrl, trimmedKey);
	}

	function selectConfig(config: RuntimeConfig) {
		setUrl(config.runtimeUrl);
		setError(null);
	}

	return (
		<div className="connection-setup-container">
			<div className="connection-setup">
				<div className="setup-header">
					<svg
						className="setup-logo"
						fill="none"
						height="48"
						stroke="currentColor"
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth="2"
						viewBox="0 0 24 24"
						width="48"
					>
						<title>Undefined</title>
						<circle cx="12" cy="12" r="10" />
						<path d="M8 12h8" />
						<path d="M12 8l4 4-4 4" />
					</svg>
					<h2>连接到 Undefined Runtime</h2>
					<p>请输入 Runtime 服务器地址和 API Key</p>
				</div>

				{savedConfigs.length > 0 && (
					<section className="recent-configs">
						<h3>最近使用</h3>
						<div className="config-list">
							{savedConfigs.map((config) => (
								<button
									className="config-item"
									key={config.runtimeUrl}
									onClick={() => selectConfig(config)}
									type="button"
								>
									<svg
										fill="none"
										height="16"
										stroke="currentColor"
										strokeLinecap="round"
										strokeLinejoin="round"
										strokeWidth="2"
										viewBox="0 0 24 24"
										width="16"
									>
										<title>服务器</title>
										<rect height="8" width="20" x="2" y="2" />
										<rect height="8" width="20" x="2" y="14" />
										<line x1="6" x2="6.01" y1="6" y2="6" />
										<line x1="6" x2="6.01" y1="18" y2="18" />
									</svg>
									<span>{config.runtimeUrl}</span>
								</button>
							))}
						</div>
					</section>
				)}

				<form onSubmit={handleConnect}>
					<label>
						<span className="label-text">Runtime URL</span>
						<input
							autoComplete="url"
							onChange={(event) => setUrl(event.currentTarget.value)}
							placeholder="http://192.168.1.100:8788"
							required
							type="url"
							value={url}
						/>
					</label>

					<label>
						<span className="label-text">API Key</span>
						<input
							autoComplete="current-password"
							onChange={(event) => setApiKey(event.currentTarget.value)}
							placeholder="请输入 API Key"
							required
							type="password"
							value={apiKey}
						/>
					</label>

					{error ? <p className="setup-error">{error}</p> : null}

					<button className="connect-button" type="submit">
						连接
					</button>
				</form>

				<div className="setup-hint">
					<svg
						fill="none"
						height="16"
						stroke="currentColor"
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth="2"
						viewBox="0 0 24 24"
						width="16"
					>
						<title>提示</title>
						<circle cx="12" cy="12" r="10" />
						<path d="M12 16v-4" />
						<path d="M12 8h.01" />
					</svg>
					<p>
						提示：Runtime URL 通常是局域网 IP 地址（如
						http://192.168.1.100:8788），请确保设备在同一网络下。
					</p>
				</div>
			</div>
		</div>
	);
}
