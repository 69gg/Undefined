import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "../i18n";

export type RuntimeConfig = {
	runtimeUrl: string;
	usedAt: number;
};

export type ConnectionSetupProps = {
	/**
	 * 模式：
	 * - "setup"：首次连接（需要 URL + API Key，无关闭按钮）
	 * - "settings"：已连接后修改配置（API Key 可留空保持原值，可关闭）
	 */
	mode: "setup" | "settings";
	/** 当前已配置的 Runtime URL（用于回填输入框） */
	currentUrl?: string;
	/** 连接/保存回调；由调用方负责 saveRuntimeConfig→保存密钥→bootstrap 等持久化逻辑 */
	onConnect: (url: string, apiKey: string, allowInsecure: boolean) => void;
	/** settings 模式下的关闭回调（setup 模式不提供） */
	onClose?: () => void;
	/** 调用方（如 bootstrap）返回的错误信息，与本组件本地校验错误合并显示 */
	error?: string | null;
	/** 额外的设置项（如自动滚动开关），渲染在面板底部；通常仅在 settings 模式使用 */
	children?: ReactNode;
};

const RUNTIME_HISTORY_KEY = "undefined-runtime-history";
const DEFAULT_SETUP_URL = "http://127.0.0.1:8788";

/** 从 localStorage 读取最近使用的 Runtime 配置（按时间倒序，最多 5 条） */
function loadSavedConfigs(): RuntimeConfig[] {
	try {
		const stored = localStorage.getItem(RUNTIME_HISTORY_KEY);
		if (!stored) {
			return [];
		}
		const parsed = JSON.parse(stored) as RuntimeConfig[];
		return parsed.sort((a, b) => b.usedAt - a.usedAt).slice(0, 5);
	} catch {
		return [];
	}
}

/** 将一个 Runtime URL 写入最近使用历史（去重 + 置顶 + 截断到 5 条） */
function saveConfigToHistory(runtimeUrl: string): void {
	try {
		const configs = loadSavedConfigs();
		const updated = [
			{ runtimeUrl, usedAt: Date.now() },
			...configs.filter((item) => item.runtimeUrl !== runtimeUrl),
		].slice(0, 5);
		localStorage.setItem(RUNTIME_HISTORY_KEY, JSON.stringify(updated));
	} catch {
		// 忽略存储异常（隐私模式 / 配额）
	}
}

/**
 * 统一连接 / 配置组件
 *
 * 同时承担首次连接（setup）与运行期配置修改（settings）两种场景：
 * - Runtime URL / API Key 输入、"允许不安全存储降级" 复选框
 * - 最近使用历史（点击回填）
 * - 本地校验（URL 必填且格式合法、setup 模式 API Key 必填）
 * - 全部文案走 i18n
 *
 * 持久化逻辑（保存配置、保存密钥、bootstrap）由调用方在 onConnect 中完成。
 */
export function ConnectionSetup({
	mode,
	currentUrl,
	onConnect,
	onClose,
	error,
	children,
}: ConnectionSetupProps) {
	const { t } = useTranslation();
	const isSetup = mode === "setup";
	const [url, setUrl] = useState(currentUrl ?? DEFAULT_SETUP_URL);
	const [apiKey, setApiKey] = useState("");
	const [allowInsecure, setAllowInsecure] = useState(false);
	const [savedConfigs, setSavedConfigs] = useState<RuntimeConfig[]>([]);
	const [localError, setLocalError] = useState<string | null>(null);

	useEffect(() => {
		setSavedConfigs(loadSavedConfigs());
	}, []);

	// 调用方回填的 URL 变化时同步（如 bootstrap 后拿到已存配置）
	useEffect(() => {
		if (currentUrl) {
			setUrl(currentUrl);
		}
	}, [currentUrl]);

	function handleSubmit(event: FormEvent<HTMLFormElement>): void {
		event.preventDefault();
		setLocalError(null);

		const trimmedUrl = url.trim();
		const trimmedKey = apiKey.trim();

		if (!trimmedUrl) {
			setLocalError(t("setup.error.needUrl"));
			return;
		}
		// setup 模式必须填写 API Key；settings 模式留空表示沿用原密钥
		if (isSetup && !trimmedKey) {
			setLocalError(t("setup.error.needApiKey"));
			return;
		}
		try {
			new URL(trimmedUrl);
		} catch {
			setLocalError(t("setup.error.invalidUrl"));
			return;
		}

		saveConfigToHistory(trimmedUrl);
		setSavedConfigs(loadSavedConfigs());
		onConnect(trimmedUrl, trimmedKey, allowInsecure);
		setApiKey("");
	}

	function selectConfig(config: RuntimeConfig): void {
		setUrl(config.runtimeUrl);
		setLocalError(null);
	}

	const displayError = localError ?? error ?? null;

	return (
		<div className="setup-panel-container">
			<form className="setup-panel" onSubmit={handleSubmit}>
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						alignItems: "center",
					}}
				>
					<h3>
						{isSetup
							? t("setup.dialog.connectTitle")
							: t("setup.dialog.configTitle")}
					</h3>
					{!isSetup && onClose ? (
						<button
							aria-label={t("setup.close")}
							className="icon-button"
							onClick={onClose}
							style={{
								border: "none",
								boxShadow: "none",
								fontSize: "1.2rem",
							}}
							title={t("setup.close")}
							type="button"
						>
							×
						</button>
					) : null}
				</div>

				{savedConfigs.length > 0 ? (
					<section className="recent-configs">
						<h3>{t("setup.recent")}</h3>
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
										<title>{t("setup.server")}</title>
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
				) : null}

				<label>
					<span>{t("setup.urlLabel")}</span>
					<input
						autoComplete="url"
						onChange={(event) => {
							setUrl(event.currentTarget.value);
							setLocalError(null);
						}}
						placeholder={DEFAULT_SETUP_URL}
						type="text"
						value={url}
					/>
				</label>
				<label>
					<span>{t("setup.apiKeyLabel")}</span>
					<input
						autoComplete="current-password"
						onChange={(event) => {
							setApiKey(event.currentTarget.value);
							setLocalError(null);
						}}
						placeholder={
							isSetup ? t("setup.apiKey.placeholder") : t("setup.apiKey.masked")
						}
						type="password"
						value={apiKey}
					/>
				</label>
				<label className="setup-checkbox">
					<input
						checked={allowInsecure}
						onChange={(event) => setAllowInsecure(event.currentTarget.checked)}
						type="checkbox"
					/>
					<span>{t("setup.allowInsecureFallback")}</span>
				</label>
				<button type="submit">{t("setup.submit")}</button>
				<p>{t("setup.insecureHint")}</p>
				{displayError ? (
					<strong style={{ color: "var(--status-error-text)" }}>
						{displayError}
					</strong>
				) : null}
				{children}
			</form>
		</div>
	);
}
