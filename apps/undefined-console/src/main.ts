import { isTauri } from "@tauri-apps/api/core";
import { fetch as nativeFetch } from "@tauri-apps/plugin-http";
import "./style.css";

type ConnectionMode = "management" | "runtime";
type Lang = "zh" | "en";
type Theme = "light" | "dark";
type ProbeKind = "management" | "runtime" | "profile" | "configuration";

type ConnectionProfile = {
	id: string;
	name: string;
	mode: ConnectionMode;
	managementUrl: string;
	runtimeUrl: string;
	apiKey: string;
	password: string;
	notes: string;
};

type ProbeState = {
	kind: ProbeKind;
	status: "idle" | "ok" | "error";
	summary: string;
	detail: string;
};

const PROFILE_STORAGE_KEY = "undefined.console.profiles";
const PREFERENCE_STORAGE_KEY = "undefined.console.preferences";

const messages = {
	zh: {
		brand: "Undefined Console",
		subtitle: "保存连接、测试端点，然后直接进入真正的 WebUI。",
		lang_toggle: "English",
		theme_light: "浅色",
		theme_dark: "深色",
		hero_title: "连接后直接打开远程 WebUI",
		hero_copy:
			"Tauri 只负责保存连接与做基础探测；真正的管理界面直接使用现有 WebUI，因此样式和功能与浏览器版保持一致。",
		button_open: "打开 WebUI",
		button_test: "测试连接",
		button_seed: "填入本地示例",
		button_save: "保存连接",
		save_success: "保存成功",
		button_new: "新建连接",
		button_use: "使用",
		button_delete: "删除",
		nav_probes: "探针",
		saved_profiles: "已保存连接",
		saved_profiles_copy: "连接配置保存在当前设备本地。",
		editor_title: "连接编辑器",
		editor_copy:
			"管理模式用于打开完整 WebUI；运行态模式只用于探测 Runtime API。",
		display_name: "显示名称",
		mode: "连接模式",
		mode_management: "管理模式",
		mode_runtime: "仅运行态",
		management_url: "Management 地址",
		runtime_url: "Runtime 地址",
		password: "管理密码",
		password_placeholder: "用于测试管理登录",
		api_key: "Runtime API Key",
		api_key_placeholder: "仅运行态探测时使用",
		notes: "备注",
		notes_placeholder: "例如：本机、预发布、Android 备用连接",
		launcher_hint: "如果你想要完整功能和完整 UI，请直接打开远程 WebUI。",
		empty_profiles: "还没有保存的连接。",
		empty_probes: "点击“测试连接”后，这里会显示探针结果。",
		profile_default_name: "本地管理入口",
		profile_default_notes: "推荐默认项，连接本机 Undefined-webui。",
		profile_seed_name: "本地 Runtime 示例",
		profile_seed_notes: "用于直接检查本地 Runtime API。",
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
		unauthorized_hint: "未授权；如果是管理模式，请填写密码。",
		config_missing: "还没有配置任何端点",
		config_missing_detail: "请至少填写一个 Management 地址或 Runtime 地址。",
		not_configured: "未配置",
		endpoint_label: "端点",
		tried_label: "尝试地址",
		health_label: "健康检查",
		openapi_label: "OpenAPI",
		base_url_label: "基础地址",
		cannot_open: "当前连接没有 Management 地址，无法打开 WebUI。",
		opening: "正在打开远程 WebUI...",
	},
	en: {
		brand: "Undefined Console",
		subtitle: "Save connections, test endpoints, then open the real WebUI.",
		lang_toggle: "中文",
		theme_light: "Light",
		theme_dark: "Dark",
		hero_title: "Open the real remote WebUI after choosing a connection",
		hero_copy:
			"Tauri only stores connections and runs basic probes. The actual management interface uses the existing WebUI so the look and features stay aligned with the browser version.",
		button_open: "Open WebUI",
		button_test: "Test connection",
		button_seed: "Seed local",
		button_save: "Save profile",
		save_success: "Saved",
		button_new: "New profile",
		button_use: "Use",
		button_delete: "Delete",
		nav_probes: "Probes",
		saved_profiles: "Saved profiles",
		saved_profiles_copy: "Profiles are stored locally on this device.",
		editor_title: "Profile editor",
		editor_copy:
			"Management mode opens the full WebUI. Runtime-only mode is kept for Runtime API probing only.",
		display_name: "Display name",
		mode: "Mode",
		mode_management: "Management",
		mode_runtime: "Runtime-only",
		management_url: "Management URL",
		runtime_url: "Runtime URL",
		password: "Management password",
		password_placeholder: "Used for testing management login",
		api_key: "Runtime API key",
		api_key_placeholder: "Used for runtime probing only",
		notes: "Notes",
		notes_placeholder: "For example: local, staging, Android fallback",
		launcher_hint:
			"If you want the full UI and all features, open the remote WebUI directly.",
		empty_profiles: "No saved profiles yet.",
		empty_probes:
			"Probe results will appear here after you click test connection.",
		profile_default_name: "Local Management",
		profile_default_notes:
			"Recommended default. Connect to local Undefined-webui.",
		profile_seed_name: "Local Runtime seed",
		profile_seed_notes: "Use this to inspect a local Runtime API directly.",
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
		unauthorized_hint: "Unauthorized; add a password for management mode.",
		config_missing: "No endpoints configured",
		config_missing_detail: "Add a Management URL or Runtime URL.",
		not_configured: "Not configured",
		endpoint_label: "Endpoint",
		tried_label: "Tried",
		health_label: "Health",
		openapi_label: "OpenAPI",
		base_url_label: "Base URL",
		cannot_open:
			"This profile has no Management URL, so WebUI cannot be opened.",
		opening: "Opening remote WebUI...",
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

function loadProfiles(): ConnectionProfile[] {
	const raw = localStorage.getItem(PROFILE_STORAGE_KEY);
	if (!raw) {
		return [
			{
				id: crypto.randomUUID(),
				name: messages.zh.profile_default_name,
				mode: "management",
				managementUrl: "http://127.0.0.1:8787",
				runtimeUrl: "http://127.0.0.1:8788",
				apiKey: "",
				password: "",
				notes: messages.zh.profile_default_notes,
			},
		];
	}
	try {
		const parsed = JSON.parse(raw) as ConnectionProfile[];
		return Array.isArray(parsed) ? parsed : [];
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

function normalizeUrl(value: string): string {
	return value.trim().replace(/\/$/, "");
}

function modeLabel(mode: ConnectionMode): string {
	return mode === "management" ? t("mode_management") : t("mode_runtime");
}

function probeKindLabel(kind: ProbeKind): string {
	if (kind === "management") return t("management_kind");
	if (kind === "runtime") return t("runtime_kind");
	if (kind === "profile") return t("profile_kind");
	return t("configuration_kind");
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

async function open_webui(): Promise<void> {
	const profile = selectedProfile();
	if (!profile?.managementUrl) {
		state.infoMessage = t("cannot_open");
		render();
		return;
	}
	state.infoMessage = t("opening");
	render();
	window.location.assign(normalizeUrl(profile.managementUrl));
}

async function run_probes(): Promise<void> {
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
	if (profile.managementUrl) probes.push(await probe_management(profile));
	if (profile.runtimeUrl) probes.push(await probe_runtime(profile));
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

async function probe_management(
	profile: ConnectionProfile,
): Promise<ProbeState> {
	const base = normalizeUrl(profile.managementUrl);
	const loginUrl = `${base}/api/v1/management/auth/login`;
	const capabilityUrl = `${base}/api/v1/management/probes/capabilities`;
	const sessionUrl = `${base}/api/v1/management/auth/session`;
	let headers: Record<string, string> | undefined;
	let loginDetail = "";

	if (profile.password) {
		try {
			const loginResp = await request(loginUrl, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ password: profile.password }),
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
			if (response.status === 401 && !profile.password) {
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

async function probe_runtime(profile: ConnectionProfile): Promise<ProbeState> {
	const base = normalizeUrl(profile.runtimeUrl);
	const headers = profile.apiKey
		? { "X-Undefined-API-Key": profile.apiKey }
		: undefined;
	try {
		const health = await request(`${base}/health`, { headers });
		const healthText = await health.text();
		const openapi = await request(`${base}/openapi.json`, { headers });
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
					const target =
						entry.mode === "management"
							? entry.managementUrl
							: entry.runtimeUrl;
					return `
                    <article class="connection-card" data-profile-id="${entry.id}">
                        <div class="connection-head">
                            <div>
                                <strong>${escapeHtml(entry.name)}</strong>
                                <div class="connection-meta">${escapeHtml(modeLabel(entry.mode))} · ${escapeHtml(target || t("not_configured"))}</div>
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

	const activeMode = profile?.mode ?? "management";

	app.innerHTML = `
        <div class="shell launcher-shell">
            <main class="content launcher-content">
                <header class="launcher-header">
                    <div>
                        <div class="brand"><span class="brand-dot"></span><span>${t("brand")}</span></div>
                        <p class="panel-copy launcher-subtitle">${t("subtitle")}</p>
                    </div>
                    <div class="sidebar-actions">
                        <button class="pref-chip" type="button" data-action="toggle-lang">${t("lang_toggle")}</button>
                        <button class="pref-chip" type="button" data-action="toggle-theme">${themeButtonLabel}</button>
                    </div>
                </header>

                <section class="hero">
                    <article class="hero-card">
                        <h1 class="hero-title">${t("hero_title")}</h1>
                        <p class="hero-subtitle">${t("hero_copy")}</p>
                        <div class="button-row hero-button-row">
                            <button class="primary" type="button" data-action="open-webui">${t("button_open")}</button>
                            <button class="secondary" type="button" data-action="test-connection">${t("button_test")}</button>
                            <button class="secondary" type="button" data-action="seed-local">${t("button_seed")}</button>
                        </div>
                        ${state.infoMessage ? `<div class="connection-meta launcher-message">${escapeHtml(state.infoMessage)}</div>` : ""}
                    </article>

                    <div class="layout-grid launcher-grid">
                        <section class="panel">
                            <h2 class="section-title">${t("saved_profiles")}</h2>
                            <p class="panel-copy">${t("saved_profiles_copy")}</p>
                            <div class="connection-list">${connectionCards}</div>
                        </section>

                        <section class="panel">
                            <h2 class="section-title">${t("editor_title")}</h2>
                            <p class="panel-copy">${t("editor_copy")}</p>
                            <form id="profile-form" class="form-grid">
                                <div class="field">
                                    <label for="profile-name">${t("display_name")}</label>
                                    <input id="profile-name" name="name" value="${escapeAttribute(profile?.name ?? "")}" required />
                                </div>
                                <div class="field">
                                    <label for="profile-mode">${t("mode")}</label>
                                    <select id="profile-mode" name="mode">
                                        <option value="management" ${activeMode === "management" ? "selected" : ""}>${t("mode_management")}</option>
                                        <option value="runtime" ${activeMode === "runtime" ? "selected" : ""}>${t("mode_runtime")}</option>
                                    </select>
                                </div>
                                <div class="field full">
                                    <label for="management-url">${t("management_url")}</label>
                                    <input id="management-url" name="managementUrl" value="${escapeAttribute(profile?.managementUrl ?? "")}" placeholder="http://127.0.0.1:8787" />
                                </div>
                                <div class="field full">
                                    <label for="password">${t("password")}</label>
                                    <input id="password" type="password" name="password" value="${escapeAttribute(profile?.password ?? "")}" placeholder="${escapeAttribute(t("password_placeholder"))}" />
                                </div>
                                <div class="field full">
                                    <label for="runtime-url">${t("runtime_url")}</label>
                                    <input id="runtime-url" name="runtimeUrl" value="${escapeAttribute(profile?.runtimeUrl ?? "")}" placeholder="http://127.0.0.1:8788" />
                                </div>
                                <div class="field full">
                                    <label for="api-key">${t("api_key")}</label>
                                    <input id="api-key" name="apiKey" value="${escapeAttribute(profile?.apiKey ?? "")}" placeholder="${escapeAttribute(t("api_key_placeholder"))}" />
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
                                    <div class="input-help">${t("launcher_hint")}</div>
                                </div>
                            </form>
                        </section>
                    </div>

                    <section class="panel">
                        <h2 class="section-title">${t("nav_probes")}</h2>
                        <p class="panel-copy">${t("subtitle")}</p>
                        <div class="status-list">${probeCards}</div>
                    </section>
                </section>
            </main>
        </div>
    `;

	bind_events();
}

function bind_events(): void {
	document
		.querySelector<HTMLFormElement>("#profile-form")
		?.addEventListener("submit", (event) => {
			event.preventDefault();
			const form = new FormData(event.currentTarget as HTMLFormElement);
			const nextProfile: ConnectionProfile = {
				id: state.selectedId || crypto.randomUUID(),
				name: String(form.get("name") || t("profile_new_name")).trim(),
				mode:
					String(form.get("mode") || "management") === "runtime"
						? "runtime"
						: "management",
				managementUrl: normalizeUrl(String(form.get("managementUrl") || "")),
				runtimeUrl: normalizeUrl(String(form.get("runtimeUrl") || "")),
				apiKey: String(form.get("apiKey") || "").trim(),
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
				mode: "management",
				managementUrl: "",
				runtimeUrl: "",
				apiKey: "",
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
				mode: "runtime",
				managementUrl: "http://127.0.0.1:8787",
				runtimeUrl: "http://127.0.0.1:8788",
				apiKey: "changeme",
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
			void open_webui();
		});

	document
		.querySelector<HTMLElement>("[data-action='test-connection']")
		?.addEventListener("click", () => {
			void run_probes();
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
