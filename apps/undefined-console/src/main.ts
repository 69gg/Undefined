import { isTauri } from "@tauri-apps/api/core";
import { fetch as nativeFetch } from "@tauri-apps/plugin-http";
import "./style.css";

type ConnectionMode = "management" | "runtime";
type Lang = "zh" | "en";
type Theme = "light" | "dark";
type ActiveTab = "connections" | "diagnostics" | "about";
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
		sidebar_copy:
			"适合连接 Undefined-webui 管理入口，也可保留 Runtime-only 连接做只读排障。",
		nav_connections: "连接",
		nav_diagnostics: "探针",
		nav_about: "关于",
		lang_toggle: "English",
		theme_light: "浅色",
		theme_dark: "深色",
		hero_meta: "跨平台 Tauri 控制台",
		hero_title: "远程管理优先的 Undefined 控制台",
		hero_subtitle:
			"默认中文亮色；优先使用管理模式处理配置、日志、启动与救援流程。",
		test_connection: "测试连接",
		seed_local: "填入本地示例",
		saved_profiles: "已保存连接",
		saved_profiles_copy: "连接配置保存在当前设备本地。",
		profile_editor: "连接编辑器",
		profile_editor_copy:
			"管理模式推荐填写 Management 地址与密码；仅运行态模式则填写 Runtime 地址与 API Key。",
		display_name: "显示名称",
		mode: "连接模式",
		mode_management: "管理模式",
		mode_runtime: "仅运行态",
		management_url: "Management 地址",
		runtime_url: "Runtime 地址",
		api_key: "Runtime API Key",
		api_key_placeholder: "仅运行态探测时使用",
		password: "管理密码",
		password_placeholder: "用于登录 Management API",
		notes: "备注",
		notes_placeholder: "例如：本机、预发布、Android 备用连接",
		save_profile: "保存连接",
		new_profile: "新建连接",
		profile_help: "管理模式下会优先尝试登录并探测 capabilities / session。",
		diagnostics: "探针结果",
		diagnostics_copy:
			"优先探测 Management API；如果配置了 Runtime 地址，也会同时探测运行态健康与 OpenAPI。",
		empty_profiles: "还没有保存的连接，先创建一个。",
		empty_probes: "点击“测试连接”后，这里会显示探针结果。",
		badge_active: "当前使用",
		badge_saved: "已保存",
		button_use: "使用",
		button_delete: "删除",
		mobile_profiles: "连接",
		mobile_probe: "探针",
		mobile_about: "关于",
		profile_default_name: "本地管理入口",
		profile_default_notes: "推荐默认项，连接本机 Undefined-webui。",
		profile_new_name: "新连接",
		profile_seed_name: "本地 Runtime 示例",
		profile_seed_notes: "用于直接检查本地 Runtime API。",
		profile_empty: "未选择连接",
		profile_missing: "请先新建或选择一个连接。",
		config_missing: "还没有配置任何端点",
		config_missing_detail:
			"请至少填写一个 Management 地址或 Runtime 地址后再测试。",
		management_kind: "Management API",
		runtime_kind: "Runtime API",
		profile_kind: "连接状态",
		configuration_kind: "配置状态",
		probe_failed: "探测失败",
		endpoint_unreachable: "端点不可达",
		unknown_failure: "探测过程中发生未知错误。",
		about_title: "关于",
		about_copy:
			"这是 Undefined 的跨平台控制台骨架，面向桌面端与 Android，默认作为 Management API 客户端使用。",
		about_highlight_one: "支持中英双语切换。",
		about_highlight_two: "支持亮暗主题切换。",
		about_highlight_three: "侧边栏固定，主内容独立滚动。",
		status_idle: "待检测",
		status_ok: "正常",
		status_error: "异常",
		not_configured: "未配置",
		health_label: "健康检查",
		openapi_label: "OpenAPI",
		endpoint_label: "端点",
		tried_label: "尝试地址",
		base_url_label: "基础地址",
		management_status_prefix: "管理端返回",
		runtime_status_prefix: "运行态返回",
		unauthorized_hint: "未授权；如果是管理模式，请填写密码。",
	},
	en: {
		brand: "Undefined Console",
		sidebar_copy:
			"Best used with Undefined-webui as the management entry, while keeping runtime-only profiles for read-only troubleshooting.",
		nav_connections: "Connections",
		nav_diagnostics: "Diagnostics",
		nav_about: "About",
		lang_toggle: "中文",
		theme_light: "Light",
		theme_dark: "Dark",
		hero_meta: "Cross-platform Tauri shell",
		hero_title: "Remote-first management console for Undefined",
		hero_subtitle:
			"Defaults to Chinese + light theme. Use management mode for config, logs, startup, and rescue flows.",
		test_connection: "Test connection",
		seed_local: "Seed local defaults",
		saved_profiles: "Saved profiles",
		saved_profiles_copy: "Profiles are stored locally on this device.",
		profile_editor: "Profile editor",
		profile_editor_copy:
			"Management mode should include a Management URL and password. Runtime-only mode should use a Runtime URL and API key.",
		display_name: "Display name",
		mode: "Mode",
		mode_management: "Management",
		mode_runtime: "Runtime-only",
		management_url: "Management URL",
		runtime_url: "Runtime URL",
		api_key: "Runtime API key",
		api_key_placeholder: "Used for runtime-only probing",
		password: "Management password",
		password_placeholder: "Used to log in to Management API",
		notes: "Notes",
		notes_placeholder: "For example: local, staging, Android fallback",
		save_profile: "Save profile",
		new_profile: "New profile",
		profile_help:
			"Management mode tries to log in first, then probes capabilities and session.",
		diagnostics: "Diagnostics",
		diagnostics_copy:
			"The app probes Management API first, then checks runtime health/OpenAPI if a runtime URL is configured.",
		empty_profiles: "No saved profiles yet. Create one first.",
		empty_probes:
			"Probe results will appear here after you click test connection.",
		badge_active: "ACTIVE",
		badge_saved: "SAVED",
		button_use: "Use",
		button_delete: "Delete",
		mobile_profiles: "Profiles",
		mobile_probe: "Probe",
		mobile_about: "About",
		profile_default_name: "Local Management",
		profile_default_notes:
			"Recommended default. Connect to local Undefined-webui.",
		profile_new_name: "New profile",
		profile_seed_name: "Local Runtime seed",
		profile_seed_notes: "Use this to inspect a local Runtime API directly.",
		profile_empty: "No active profile",
		profile_missing: "Create or select a saved profile first.",
		config_missing: "No endpoints configured",
		config_missing_detail:
			"Add a Management URL or Runtime URL before testing.",
		management_kind: "Management API",
		runtime_kind: "Runtime API",
		profile_kind: "Profile",
		configuration_kind: "Configuration",
		probe_failed: "Probe failed",
		endpoint_unreachable: "Endpoint unreachable",
		unknown_failure: "Unknown error during probe.",
		about_title: "About",
		about_copy:
			"This is the cross-platform console scaffold for Undefined, intended for desktop and Android as a Management API client.",
		about_highlight_one: "Supports Chinese / English UI switching.",
		about_highlight_two: "Supports light / dark theme switching.",
		about_highlight_three:
			"Pinned sidebar with independently scrolling content.",
		status_idle: "Idle",
		status_ok: "Healthy",
		status_error: "Error",
		not_configured: "Not configured",
		health_label: "Health",
		openapi_label: "OpenAPI",
		endpoint_label: "Endpoint",
		tried_label: "Tried",
		base_url_label: "Base URL",
		management_status_prefix: "Management returned",
		runtime_status_prefix: "Runtime returned",
		unauthorized_hint:
			"Unauthorized; if this is a management profile, add a password.",
	},
} as const;

type MessageKey = keyof typeof messages.zh;

const state = {
	lang: loadPreference("lang", "zh" as Lang),
	theme: loadPreference("theme", "light" as Theme),
	activeTab: "connections" as ActiveTab,
	profiles: loadProfiles(),
	selectedId: "",
	probes: [] as ProbeState[],
};

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

if (!state.selectedId) {
	state.selectedId = state.profiles[0]?.id ?? "";
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

function modeLabel(mode: ConnectionMode): string {
	return mode === "management" ? t("mode_management") : t("mode_runtime");
}

function probeKindLabel(kind: ProbeKind): string {
	if (kind === "management") return t("management_kind");
	if (kind === "runtime") return t("runtime_kind");
	if (kind === "profile") return t("profile_kind");
	return t("configuration_kind");
}

function badge(probe: ProbeState): string {
	const label =
		probe.status === "ok"
			? t("status_ok")
			: probe.status === "error"
				? t("status_error")
				: t("status_idle");
	return `<span class="badge ${probe.status}">${escapeHtml(label)}</span>`;
}

function normalizeUrl(value: string): string {
	return value.trim().replace(/\/$/, "");
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

function setTab(tab: ActiveTab): void {
	state.activeTab = tab;
	render();
}

function render(): void {
	applyPreferences();
	const profile = selectedProfile();
	const app = document.querySelector<HTMLDivElement>("#app");
	if (!app) return;

	const themeButtonLabel =
		state.theme === "light" ? t("theme_dark") : t("theme_light");
	const activeMode = profile?.mode ?? "management";

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
								<span class="badge ${active ? "ok" : "idle"}">${active ? t("badge_active") : t("badge_saved")}</span>
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
								${badge(probe)}
							</div>
							<div class="status-meta">${escapeHtml(probe.summary)}</div>
							<pre>${escapeHtml(probe.detail)}</pre>
						</div>
					`,
				)
				.join("")
		: `<div class="empty-state">${t("empty_probes")}</div>`;

	app.innerHTML = `
		<div class="shell">
			<aside class="sidebar">
				<div class="sidebar-top">
					<div class="brand"><span class="brand-dot"></span><span>${t("brand")}</span></div>
					<div class="sidebar-actions">
						<button class="pref-chip" type="button" data-action="toggle-lang">${t("lang_toggle")}</button>
						<button class="pref-chip" type="button" data-action="toggle-theme">${themeButtonLabel}</button>
					</div>
					<p class="sidebar-copy">${t("sidebar_copy")}</p>
					<div class="nav-stack">
						<button class="nav-button ${state.activeTab === "connections" ? "active" : ""}" type="button" data-tab="connections">${t("nav_connections")}</button>
						<button class="nav-button ${state.activeTab === "diagnostics" ? "active" : ""}" type="button" data-tab="diagnostics">${t("nav_diagnostics")}</button>
						<button class="nav-button ${state.activeTab === "about" ? "active" : ""}" type="button" data-tab="about">${t("nav_about")}</button>
					</div>
				</div>
			</aside>
			<main class="content">
				<section class="hero">
					<article class="hero-card ${state.activeTab !== "connections" ? "is-hidden" : ""}">
						<div class="hero-meta-row">
							<p class="connection-meta">${t("hero_meta")}</p>
							<div class="hero-actions-mobile">
								<button class="pref-chip" type="button" data-action="toggle-lang">${t("lang_toggle")}</button>
								<button class="pref-chip" type="button" data-action="toggle-theme">${themeButtonLabel}</button>
							</div>
						</div>
						<h1 class="hero-title">${t("hero_title")}</h1>
						<p class="hero-subtitle">${t("hero_subtitle")}</p>
						<div class="button-row hero-button-row">
							<button class="primary" type="button" data-action="test-connection">${t("test_connection")}</button>
							<button class="secondary" type="button" data-action="seed-local">${t("seed_local")}</button>
						</div>
					</article>

					<section class="panel ${state.activeTab !== "connections" ? "is-hidden" : ""}">
						<h2 class="section-title">${t("saved_profiles")}</h2>
						<p class="panel-copy">${t("saved_profiles_copy")}</p>
						<div class="connection-list">${connectionCards}</div>
					</section>

					<section class="panel ${state.activeTab !== "connections" ? "is-hidden" : ""}">
						<h2 class="section-title">${t("profile_editor")}</h2>
						<p class="panel-copy">${t("profile_editor_copy")}</p>
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
									<button class="primary" type="submit">${t("save_profile")}</button>
									<button class="secondary" type="button" data-action="new-profile">${t("new_profile")}</button>
								</div>
								<div class="input-help">${t("profile_help")}</div>
							</div>
						</form>
					</section>

					<section class="panel ${state.activeTab !== "diagnostics" ? "is-hidden" : ""}">
						<h2 class="section-title">${t("diagnostics")}</h2>
						<p class="panel-copy">${t("diagnostics_copy")}</p>
						<div class="button-row diagnostics-toolbar">
							<button class="primary" type="button" data-action="test-connection">${t("test_connection")}</button>
						</div>
						<div class="status-list">${probeCards}</div>
					</section>

					<section class="panel about-panel ${state.activeTab !== "about" ? "is-hidden" : ""}">
						<h2 class="section-title">${t("about_title")}</h2>
						<p class="panel-copy">${t("about_copy")}</p>
						<div class="about-grid">
							<div class="about-pill">${t("about_highlight_one")}</div>
							<div class="about-pill">${t("about_highlight_two")}</div>
							<div class="about-pill">${t("about_highlight_three")}</div>
						</div>
					</section>
				</section>
			</main>
			<nav class="mobile-tabbar">
				<button class="${state.activeTab === "connections" ? "active" : ""}" type="button" data-tab="connections">${t("mobile_profiles")}</button>
				<button class="${state.activeTab === "diagnostics" ? "active" : ""}" type="button" data-tab="diagnostics">${t("mobile_probe")}</button>
				<button class="${state.activeTab === "about" ? "active" : ""}" type="button" data-tab="about">${t("mobile_about")}</button>
			</nav>
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
			state.activeTab = "connections";
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
			persistProfiles();
			render();
		});
	}

	for (const button of document.querySelectorAll<HTMLElement>("[data-tab]")) {
		button.addEventListener("click", () => {
			const tab = button.dataset.tab as ActiveTab | undefined;
			if (!tab) return;
			setTab(tab);
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
			persistProfiles();
			render();
		});

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='test-connection']",
	)) {
		button.addEventListener("click", async () => {
			state.activeTab = "diagnostics";
			await runProbeSuite();
		});
	}

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='toggle-lang']",
	)) {
		button.addEventListener("click", toggleLang);
	}

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='toggle-theme']",
	)) {
		button.addEventListener("click", toggleTheme);
	}
}

async function runProbeSuite(): Promise<void> {
	const profile = selectedProfile();
	if (!profile) {
		state.probes = [
			{
				kind: "profile",
				status: "error",
				summary: t("profile_empty"),
				detail: t("profile_missing"),
			},
		];
		render();
		return;
	}

	const probes: ProbeState[] = [];
	if (profile.managementUrl) probes.push(await probeManagement(profile));
	if (profile.runtimeUrl) probes.push(await probeRuntime(profile));
	if (probes.length === 0) {
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
				try {
					const payload = JSON.parse(loginText) as { access_token?: string };
					if (payload.access_token) {
						headers = { Authorization: `Bearer ${payload.access_token}` };
					}
				} catch {
					// ignore invalid payload
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
				summary: `${t("management_status_prefix")} ${response.status} ${response.statusText}`,
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
		summary: t("probe_failed"),
		detail: t("unknown_failure"),
	};
}

async function probeRuntime(profile: ConnectionProfile): Promise<ProbeState> {
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
			summary: `${t("runtime_status_prefix")} ${health.status} ${health.statusText}`,
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

function truncate(value: string, maxLength = 1200): string {
	return value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;
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
			if (!shouldFallback) {
				throw error;
			}
		}
	}
	return fetch(url, init);
}

render();
