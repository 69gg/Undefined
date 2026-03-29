import { isTauri } from "@tauri-apps/api/core";
import { fetch as nativeFetch } from "@tauri-apps/plugin-http";
import "./style.css";

type Lang = "zh" | "en";
type Theme = "light" | "dark";
type ProbeKind = "management" | "runtime" | "profile" | "configuration";

type ConnectionProfile = {
	id: string;
	name: string;
	host: string;
	managementPort: string;
	runtimePort: string;
	password: string;
	notes: string;
};

type ProbeState = {
	kind: ProbeKind;
	status: "idle" | "ok" | "error";
	summary: string;
	detail: string;
};

type AuthBootstrapPayload = {
	accessToken: string;
	refreshToken: string;
	accessTokenExpiresAt: number;
};

const PROFILE_STORAGE_KEY = "undefined.console.profiles";
const PREFERENCE_STORAGE_KEY = "undefined.console.preferences";

const messages = {
	zh: {
		brand: "Undefined Console",
		lang_toggle: "English",
		theme_light: "浅色",
		theme_dark: "深色",
		button_open: "打开 WebUI",
		button_test: "测试连接",
		button_seed: "填入本地示例",
		button_save: "保存连接",
		save_success: "保存成功",
		button_new: "新建连接",
		button_use: "使用",
		button_delete: "删除",
		saved_profiles: "已保存连接",
		saved_profiles_copy: "连接配置保存在当前设备本地。",
		editor_title: "连接编辑器",
		display_name: "显示名称",
		host: "IP / 域名",
		host_placeholder: "例如：192.168.2.1 或 example.com",
		management_port: "Management 端口",
		runtime_port: "Runtime 端口",
		password: "管理密码",
		password_placeholder: "填写后打开 WebUI 时会自动尝试登录",
		notes: "备注",
		notes_placeholder: "例如：本机、预发布、Android 备用连接",
		empty_profiles: "还没有保存的连接。",
		empty_probes: "点击“测试连接”后，这里会显示探针结果。",
		profile_default_name: "本地管理入口",
		profile_default_notes: "推荐默认项，连接本机 Undefined-webui。",
		profile_seed_name: "本地示例连接",
		profile_seed_notes: "用于快速填入本机 Management / Runtime 默认端口。",
		profile_new_name: "新连接",
		current_in_use: "当前使用",
		saved: "已保存",
		status_idle: "待检测",
		status_ok: "正常",
		status_error: "异常",
		management_kind: "Management API",
		runtime_kind: "Runtime API",
		profile_kind: "连接状态",
		configuration_kind: "配置状态",
		endpoint_unreachable: "端点不可达",
		unauthorized_hint:
			"未授权；如果填写了管理密码，打开 WebUI 时会自动尝试登录。",
		config_missing: "还没有配置任何端点",
		config_missing_detail: "请至少填写 IP/域名与 Management 端口。",
		not_configured: "未配置",
		endpoint_label: "端点",
		tried_label: "尝试地址",
		health_label: "健康检查",
		openapi_label: "OpenAPI",
		base_url_label: "基础地址",
		cannot_open: "当前连接缺少 IP/域名或 Management 端口，无法打开 WebUI。",
		opening: "正在打开远程 WebUI...",
		login_failed: "自动登录失败，将直接打开 WebUI 登录页。",
	},
	en: {
		brand: "Undefined Console",
		lang_toggle: "中文",
		theme_light: "Light",
		theme_dark: "Dark",
		button_open: "Open WebUI",
		button_test: "Test connection",
		button_seed: "Seed local",
		button_save: "Save profile",
		save_success: "Saved",
		button_new: "New profile",
		button_use: "Use",
		button_delete: "Delete",
		saved_profiles: "Saved profiles",
		saved_profiles_copy: "Profiles are stored locally on this device.",
		editor_title: "Profile editor",
		display_name: "Display name",
		host: "Host / IP",
		host_placeholder: "For example: 192.168.2.1 or example.com",
		management_port: "Management port",
		runtime_port: "Runtime port",
		password: "Management password",
		password_placeholder: "If filled, WebUI will try to sign in automatically",
		notes: "Notes",
		notes_placeholder: "For example: local, staging, Android fallback",
		empty_profiles: "No saved profiles yet.",
		empty_probes:
			"Probe results will appear here after you click test connection.",
		profile_default_name: "Local Management",
		profile_default_notes:
			"Recommended default. Connect to local Undefined-webui.",
		profile_seed_name: "Local seed profile",
		profile_seed_notes:
			"Use this to quickly fill the local Management / Runtime defaults.",
		profile_new_name: "New profile",
		current_in_use: "ACTIVE",
		saved: "SAVED",
		status_idle: "Idle",
		status_ok: "Healthy",
		status_error: "Error",
		management_kind: "Management API",
		runtime_kind: "Runtime API",
		profile_kind: "Profile",
		configuration_kind: "Configuration",
		endpoint_unreachable: "Endpoint unreachable",
		unauthorized_hint:
			"Unauthorized; if a password is filled, WebUI open will try to sign in automatically.",
		config_missing: "No endpoints configured",
		config_missing_detail: "Add a host/IP and Management port.",
		not_configured: "Not configured",
		endpoint_label: "Endpoint",
		tried_label: "Tried",
		health_label: "Health",
		openapi_label: "OpenAPI",
		base_url_label: "Base URL",
		cannot_open:
			"This profile is missing a host/IP or Management port, so WebUI cannot be opened.",
		opening: "Opening remote WebUI...",
		login_failed:
			"Automatic login failed. Opening the WebUI login page directly.",
	},
} as const;

type MessageKey = keyof typeof messages.zh;

const state = {
	lang: loadPreference("lang", "zh" as Lang),
	theme: loadPreference("theme", "light" as Theme),
	profiles: loadProfiles(),
	selectedId: "",
	probes: [] as ProbeState[],
	infoMessage: "",
};

if (!state.selectedId) {
	state.selectedId = state.profiles[0]?.id ?? "";
}

function t(key: MessageKey): string {
	return messages[state.lang][key] ?? key;
}

function loadPreference<T extends Lang | Theme>(
	key: "lang" | "theme",
	fallback: T,
): T {
	const raw = localStorage.getItem(PREFERENCE_STORAGE_KEY);
	if (!raw) return fallback;
	try {
		const parsed = JSON.parse(raw) as Partial<Record<"lang" | "theme", T>>;
		return parsed[key] ?? fallback;
	} catch {
		return fallback;
	}
}

function parseLegacyUrl(url: string): { host: string; port: string } {
	const text = String(url || "").trim();
	if (!text) return { host: "", port: "" };
	try {
		const parsed = new URL(text);
		return {
			host: parsed.hostname || "",
			port: parsed.port || (parsed.protocol === "https:" ? "443" : "80"),
		};
	} catch {
		return { host: "", port: "" };
	}
}

function loadProfiles(): ConnectionProfile[] {
	const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
	if (!raw) {
		return [
			{
				id: crypto.randomUUID(),
				name: messages.zh.profile_default_name,
				host: "127.0.0.1",
				managementPort: "8787",
				runtimePort: "8788",
				password: "",
				notes: messages.zh.profile_default_notes,
			},
		];
	}
	try {
		const parsed = JSON.parse(raw) as Array<Record<string, unknown>>;
		if (!Array.isArray(parsed)) return [];
		return parsed.map((item) => {
			const management = parseLegacyUrl(String(item.managementUrl || ""));
			const runtime = parseLegacyUrl(String(item.runtimeUrl || ""));
			const host = String(item.host || management.host || runtime.host || "");
			return {
				id: String(item.id || crypto.randomUUID()),
				name: String(item.name || messages.zh.profile_new_name),
				host,
				managementPort: String(
					item.managementPort || management.port || "8787",
				),
				runtimePort: String(item.runtimePort || runtime.port || "8788"),
				password: String(item.password || ""),
				notes: String(item.notes || ""),
			};
		});
	} catch {
		return [];
	}
}

function persistProfiles(): void {
	localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(state.profiles));
}

function persistPreferences(): void {
	localStorage.setItem(
		PREFERENCE_STORAGE_KEY,
		JSON.stringify({ lang: state.lang, theme: state.theme }),
	);
}

function applyPreferences(): void {
	document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
	document.documentElement.dataset.theme = state.theme;
	document
		.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
		?.setAttribute("content", state.theme === "dark" ? "#111315" : "#f6f1eb");
}

function selectedProfile(): ConnectionProfile | undefined {
	return state.profiles.find((profile) => profile.id === state.selectedId);
}

function formatHost(host: string): string {
	if (host.includes(":")) return `[${host}]`;
	return host;
}

function buildManagementUrl(profile: ConnectionProfile): string {
	const host = profile.host.trim();
	const port = profile.managementPort.trim();
	if (!host || !port) return "";
	return `http://${formatHost(host)}:${port}`;
}

function buildRuntimeUrl(profile: ConnectionProfile): string {
	const host = profile.host.trim();
	const port = profile.runtimePort.trim();
	if (!host || !port) return "";
	return `http://${formatHost(host)}:${port}`;
}

function badge(status: ProbeState["status"]): string {
	const label =
		status === "ok"
			? t("status_ok")
			: status === "error"
				? t("status_error")
				: t("status_idle");
	return `<span class="badge ${status}">${escapeHtml(label)}</span>`;
}

function probeKindLabel(kind: ProbeKind): string {
	if (kind === "management") return t("management_kind");
	if (kind === "runtime") return t("runtime_kind");
	if (kind === "profile") return t("profile_kind");
	return t("configuration_kind");
}

function toggleLang(): void {
	state.lang = state.lang === "zh" ? "en" : "zh";
	persistPreferences();
	render();
}

function toggleTheme(): void {
	state.theme = state.theme === "light" ? "dark" : "light";
	persistPreferences();
	render();
}

async function request(url: string, init: RequestInit = {}): Promise<Response> {
	if (isTauri()) {
		try {
			return await nativeFetch(url, {
				method: init.method ?? "GET",
				headers: init.headers,
				body: init.body,
			});
		} catch (error) {
			const message = String(error || "");
			const shouldFallback =
				message.includes("configured scope") ||
				message.includes("Load failed") ||
				message.includes("TypeError");
			if (!shouldFallback) throw error;
		}
	}
	return fetch(url, init);
}

function normalizeBootstrapAuthPayload(
	payload: unknown,
): AuthBootstrapPayload | null {
	if (!payload || typeof payload !== "object") return null;
	const raw = payload as Record<string, unknown> & { tokens?: unknown };
	const source =
		raw.tokens && typeof raw.tokens === "object"
			? (raw.tokens as Record<string, unknown>)
			: raw;
	const accessToken = String(
		source.access_token || source.accessToken || "",
	).trim();
	const refreshToken = String(
		source.refresh_token || source.refreshToken || "",
	).trim();
	const accessTokenExpiresAt =
		Number.parseInt(
			String(
				source.access_token_expires_at || source.accessTokenExpiresAt || "0",
			),
			10,
		) || 0;
	if (!accessToken) return null;
	return { accessToken, refreshToken, accessTokenExpiresAt };
}

function encodeBootstrapAuth(payload: AuthBootstrapPayload): string {
	const json = JSON.stringify(payload);
	const bytes = new TextEncoder().encode(json);
	let binary = "";
	for (const byte of bytes) {
		binary += String.fromCharCode(byte);
	}
	return btoa(binary)
		.replaceAll("+", "-")
		.replaceAll("/", "_")
		.replace(/=+$/u, "");
}

async function openWebui(): Promise<void> {
	state.infoMessage = "";
	const profile = selectedProfile();
	if (!profile) {
		state.infoMessage = t("cannot_open");
		render();
		return;
	}
	const base = buildManagementUrl(profile);
	if (!base) {
		state.infoMessage = t("cannot_open");
		render();
		return;
	}

	const target = new URL(base);
	target.searchParams.set("lang", state.lang);
	target.searchParams.set("theme", state.theme);
	target.searchParams.set("tab", "overview");
	target.searchParams.set("view", "app");
	target.searchParams.set("client", "native");
	target.searchParams.set("return_to", window.location.href);

	let bootstrapAuth: AuthBootstrapPayload | null = null;
	if (profile.password.trim()) {
		try {
			const loginResponse = await request(
				`${base}/api/v1/management/auth/login`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ password: profile.password.trim() }),
				},
			);
			if (loginResponse.ok) {
				const loginPayload = await loginResponse
					.clone()
					.json()
					.catch(() => null);
				bootstrapAuth = normalizeBootstrapAuthPayload(loginPayload);
			}
			if (!bootstrapAuth) {
				state.infoMessage = t("login_failed");
			}
		} catch {
			state.infoMessage = t("login_failed");
		}
	}

	if (bootstrapAuth) {
		target.hash = `auth=${encodeBootstrapAuth(bootstrapAuth)}`;
	}

	state.infoMessage = state.infoMessage || t("opening");
	render();
	window.location.assign(target.toString());
}

async function runProbes(): Promise<void> {
	const profile = selectedProfile();
	if (!profile) {
		state.probes = [
			{
				kind: "profile",
				status: "error",
				summary: t("not_configured"),
				detail: t("empty_profiles"),
			},
		];
		render();
		return;
	}

	const probes: ProbeState[] = [];
	const managementUrl = buildManagementUrl(profile);
	const runtimeUrl = buildRuntimeUrl(profile);
	if (managementUrl)
		probes.push(await probeManagement(managementUrl, profile.password));
	if (runtimeUrl) probes.push(await probeRuntime(runtimeUrl));
	if (!probes.length) {
		probes.push({
			kind: "configuration",
			status: "error",
			summary: t("config_missing"),
			detail: t("config_missing_detail"),
		});
	}
	state.probes = probes;
	render();
}

async function probeManagement(
	base: string,
	password: string,
): Promise<ProbeState> {
	const loginUrl = `${base}/api/v1/management/auth/login`;
	const capabilityUrl = `${base}/api/v1/management/probes/capabilities`;
	const sessionUrl = `${base}/api/v1/management/auth/session`;
	let headers: Record<string, string> | undefined;
	let loginDetail = "";

	if (password.trim()) {
		try {
			const loginResp = await request(loginUrl, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ password }),
			});
			const loginText = await loginResp.text();
			loginDetail = `${t("endpoint_label")}: ${loginUrl}\n\n${truncate(loginText)}`;
			if (loginResp.ok) {
				const payload = JSON.parse(loginText) as { access_token?: string };
				if (payload.access_token) {
					headers = { Authorization: `Bearer ${payload.access_token}` };
				}
			}
		} catch (error) {
			return {
				kind: "management",
				status: "error",
				summary: t("endpoint_unreachable"),
				detail: `${t("tried_label")}: ${loginUrl}\n\n${String(error)}`,
			};
		}
	}

	for (const endpoint of [capabilityUrl, sessionUrl, `${base}/`]) {
		try {
			const response = await request(endpoint, { method: "GET", headers });
			const text = await response.text();
			const detailParts = [
				`${t("endpoint_label")}: ${endpoint}`,
				truncate(text),
			];
			if (loginDetail) detailParts.unshift(loginDetail);
			if (response.status === 401 && !password.trim()) {
				detailParts.push(t("unauthorized_hint"));
			}
			return {
				kind: "management",
				status: response.ok ? "ok" : "error",
				summary: `${t("management_kind")} · ${response.status} ${response.statusText}`,
				detail: detailParts.join("\n\n"),
			};
		} catch (error) {
			if (endpoint === `${base}/`) {
				return {
					kind: "management",
					status: "error",
					summary: t("endpoint_unreachable"),
					detail: `${t("tried_label")}: ${endpoint}\n\n${String(error)}`,
				};
			}
		}
	}

	return {
		kind: "management",
		status: "error",
		summary: t("endpoint_unreachable"),
		detail: t("endpoint_unreachable"),
	};
}

async function probeRuntime(base: string): Promise<ProbeState> {
	try {
		const health = await request(`${base}/health`);
		const healthText = await health.text();
		const openapi = await request(`${base}/openapi.json`);
		const openapiText = await openapi.text();
		return {
			kind: "runtime",
			status: health.ok ? "ok" : "error",
			summary: `${t("runtime_kind")} · ${health.status} ${health.statusText}`,
			detail: `${t("health_label")}: ${truncate(healthText)}\n\n${t("openapi_label")}: ${truncate(openapiText)}`,
		};
	} catch (error) {
		return {
			kind: "runtime",
			status: "error",
			summary: t("endpoint_unreachable"),
			detail: `${t("base_url_label")}: ${base}\n\n${String(error)}`,
		};
	}
}

function render(): void {
	applyPreferences();
	const profile = selectedProfile();
	const app = document.querySelector<HTMLDivElement>("#app");
	if (!app) return;
	const themeButtonLabel =
		state.theme === "light" ? t("theme_dark") : t("theme_light");

	const connectionCards = state.profiles.length
		? state.profiles
				.map((entry) => {
					const active = entry.id === state.selectedId;
					const summary = `${entry.host || t("not_configured")} · ${entry.managementPort || "-"} / ${entry.runtimePort || "-"}`;
					return `
                    <article class="connection-card" data-profile-id="${entry.id}">
                        <div class="connection-head">
                            <div>
                                <strong>${escapeHtml(entry.name)}</strong>
                                <div class="connection-meta">${escapeHtml(summary)}</div>
                            </div>
                            <span class="badge ${active ? "ok" : "idle"}">${active ? t("current_in_use") : t("saved")}</span>
                        </div>
                        <p class="panel-copy">${escapeHtml(entry.notes || "")}</p>
                        <div class="button-row">
                            <button class="secondary" type="button" data-action="select-profile" data-profile-id="${entry.id}">${t("button_use")}</button>
                            <button class="ghost" type="button" data-action="delete-profile" data-profile-id="${entry.id}">${t("button_delete")}</button>
                        </div>
                    </article>
                `;
				})
				.join("")
		: `<div class="empty-state">${t("empty_profiles")}</div>`;

	const probeCards = state.probes.length
		? state.probes
				.map(
					(probe) => `
                    <div class="status-card connection-card">
                        <div class="status-row">
                            <strong>${escapeHtml(probeKindLabel(probe.kind))}</strong>
                            ${badge(probe.status)}
                        </div>
                        <div class="status-meta">${escapeHtml(probe.summary)}</div>
                        <pre>${escapeHtml(probe.detail)}</pre>
                    </div>
                `,
				)
				.join("")
		: `<div class="empty-state">${t("empty_probes")}</div>`;

	app.innerHTML = `
        <div class="launcher-shell">
            <main class="launcher-content">
                <header class="launcher-header">
                    <div>
                        <div class="brand"><span class="brand-dot"></span><span>${t("brand")}</span></div>
                    </div>
                    <div class="sidebar-actions">
                        <button class="pref-chip" type="button" data-action="toggle-lang">${t("lang_toggle")}</button>
                        <button class="pref-chip" type="button" data-action="toggle-theme">${themeButtonLabel}</button>
                    </div>
                </header>

                <section class="hero">
                    <article class="hero-card">
                        <div class="button-row">
                            <button class="primary" type="button" data-action="open-webui">${t("button_open")}</button>
                            <button class="secondary" type="button" data-action="test-connection">${t("button_test")}</button>
                            <button class="secondary" type="button" data-action="seed-local">${t("button_seed")}</button>
                        </div>
                        ${state.infoMessage ? `<div class="connection-meta launcher-message">${escapeHtml(state.infoMessage)}</div>` : ""}
                    </article>

                    <div class="launcher-grid">
                        <section class="panel">
                            <h2 class="section-title">${t("saved_profiles")}</h2>
                            <p class="panel-copy">${t("saved_profiles_copy")}</p>
                            <div class="connection-list">${connectionCards}</div>
                        </section>

                        <section class="panel">
                            <h2 class="section-title">${t("editor_title")}</h2>
                            <form id="profile-form" class="form-grid">
                                <div class="field">
                                    <label for="profile-name">${t("display_name")}</label>
                                    <input id="profile-name" name="name" value="${escapeAttribute(profile?.name ?? "")}" required />
                                </div>
                                <div class="field">
                                    <label for="host">${t("host")}</label>
                                    <input id="host" name="host" value="${escapeAttribute(profile?.host ?? "")}" placeholder="${escapeAttribute(t("host_placeholder"))}" />
                                </div>
                                <div class="field">
                                    <label for="management-port">${t("management_port")}</label>
                                    <input id="management-port" name="managementPort" value="${escapeAttribute(profile?.managementPort ?? "")}" inputmode="numeric" />
                                </div>
                                <div class="field">
                                    <label for="runtime-port">${t("runtime_port")}</label>
                                    <input id="runtime-port" name="runtimePort" value="${escapeAttribute(profile?.runtimePort ?? "")}" inputmode="numeric" />
                                </div>
                                <div class="field full">
                                    <label for="password">${t("password")}</label>
                                    <input id="password" type="password" name="password" value="${escapeAttribute(profile?.password ?? "")}" placeholder="${escapeAttribute(t("password_placeholder"))}" />
                                </div>
                                <div class="field full">
                                    <label for="notes">${t("notes")}</label>
                                    <textarea id="notes" name="notes" placeholder="${escapeAttribute(t("notes_placeholder"))}">${escapeHtml(profile?.notes ?? "")}</textarea>
                                </div>
                                <div class="field full">
                                    <div class="button-row">
                                        <button class="primary" type="submit">${t("button_save")}</button>
                                        <button class="secondary" type="button" data-action="new-profile">${t("button_new")}</button>
                                    </div>
                                </div>
                            </form>
                        </section>
                    </div>

                    <section class="panel">
                        <h2 class="section-title">${t("management_kind")} / ${t("runtime_kind")}</h2>
                        <div class="status-list">${probeCards}</div>
                    </section>
                </section>
            </main>
        </div>
    `;

	bindEvents();
}

function bindEvents(): void {
	document
		.querySelector<HTMLFormElement>("#profile-form")
		?.addEventListener("submit", (event) => {
			event.preventDefault();
			const form = new FormData(event.currentTarget as HTMLFormElement);
			const nextProfile: ConnectionProfile = {
				id: state.selectedId || crypto.randomUUID(),
				name: String(form.get("name") || t("profile_new_name")).trim(),
				host: String(form.get("host") || "").trim(),
				managementPort: String(form.get("managementPort") || "").trim(),
				runtimePort: String(form.get("runtimePort") || "").trim(),
				password: String(form.get("password") || "").trim(),
				notes: String(form.get("notes") || "").trim(),
			};
			const existingIndex = state.profiles.findIndex(
				(profile) => profile.id === nextProfile.id,
			);
			if (existingIndex >= 0) {
				state.profiles.splice(existingIndex, 1, nextProfile);
			} else {
				state.profiles.unshift(nextProfile);
				state.selectedId = nextProfile.id;
			}
			state.infoMessage = t("save_success");
			persistProfiles();
			render();
		});

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='select-profile']",
	)) {
		button.addEventListener("click", () => {
			const profileId = button.dataset.profileId;
			if (!profileId) return;
			state.selectedId = profileId;
			state.infoMessage = "";
			render();
		});
	}

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='delete-profile']",
	)) {
		button.addEventListener("click", () => {
			const profileId = button.dataset.profileId;
			if (!profileId) return;
			state.profiles = state.profiles.filter(
				(profile) => profile.id !== profileId,
			);
			if (state.selectedId === profileId) {
				state.selectedId = state.profiles[0]?.id ?? "";
			}
			state.infoMessage = "";
			persistProfiles();
			render();
		});
	}

	document
		.querySelector<HTMLElement>("[data-action='new-profile']")
		?.addEventListener("click", () => {
			const profile: ConnectionProfile = {
				id: crypto.randomUUID(),
				name: t("profile_new_name"),
				host: "",
				managementPort: "",
				runtimePort: "",
				password: "",
				notes: "",
			};
			state.profiles.unshift(profile);
			state.selectedId = profile.id;
			state.infoMessage = "";
			persistProfiles();
			render();
		});

	document
		.querySelector<HTMLElement>("[data-action='seed-local']")
		?.addEventListener("click", () => {
			const profile: ConnectionProfile = {
				id: crypto.randomUUID(),
				name: t("profile_seed_name"),
				host: "127.0.0.1",
				managementPort: "8787",
				runtimePort: "8788",
				password: "",
				notes: t("profile_seed_notes"),
			};
			state.profiles.unshift(profile);
			state.selectedId = profile.id;
			state.infoMessage = "";
			persistProfiles();
			render();
		});

	document
		.querySelector<HTMLElement>("[data-action='open-webui']")
		?.addEventListener("click", () => {
			void openWebui();
		});

	document
		.querySelector<HTMLElement>("[data-action='test-connection']")
		?.addEventListener("click", () => {
			void runProbes();
		});

	document
		.querySelector<HTMLElement>("[data-action='toggle-lang']")
		?.addEventListener("click", toggleLang);

	document
		.querySelector<HTMLElement>("[data-action='toggle-theme']")
		?.addEventListener("click", toggleTheme);
}

function escapeHtml(value: string): string {
	return value
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");
}

function escapeAttribute(value: string): string {
	return escapeHtml(value).replaceAll("`", "&#96;");
}

function truncate(value: string, maxLength = 1200): string {
	return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
}

render();
