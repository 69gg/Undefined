import "./style.css";

type ConnectionMode = "management" | "runtime";

type ConnectionProfile = {
	id: string;
	name: string;
	mode: ConnectionMode;
	managementUrl: string;
	runtimeUrl: string;
	apiKey: string;
	notes: string;
};

type ProbeState = {
	kind: string;
	status: "idle" | "ok" | "error";
	summary: string;
	detail: string;
};

const STORAGE_KEY = "undefined.console.profiles";

const initialProfiles = (): ConnectionProfile[] => {
	const raw = localStorage.getItem(STORAGE_KEY);
	if (!raw) {
		return [
			{
				id: crypto.randomUUID(),
				name: "Local Management",
				mode: "management",
				managementUrl: "http://127.0.0.1:8787",
				runtimeUrl: "http://127.0.0.1:8788",
				apiKey: "",
				notes: "Recommended default. Connect through Undefined-webui first.",
			},
		];
	}

	try {
		const parsed = JSON.parse(raw) as ConnectionProfile[];
		return Array.isArray(parsed) && parsed.length > 0 ? parsed : [];
	} catch {
		return [];
	}
};

const state = {
	profiles: initialProfiles(),
	selectedId: "",
	probes: [] as ProbeState[],
};

if (!state.selectedId) {
	state.selectedId = state.profiles[0]?.id ?? "";
}

const persistProfiles = () => {
	localStorage.setItem(STORAGE_KEY, JSON.stringify(state.profiles));
};

const selectedProfile = (): ConnectionProfile | undefined =>
	state.profiles.find((profile) => profile.id === state.selectedId);

const badge = (probe: ProbeState): string => {
	return `<span class="badge ${probe.status}">${probe.status.toUpperCase()}</span>`;
};

const normalizeUrl = (value: string): string => value.trim().replace(/\/$/, "");

const render = () => {
	const profile = selectedProfile();

	const app = document.querySelector<HTMLDivElement>("#app");
	if (!app) {
		return;
	}

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
                  <div class="connection-meta">${escapeHtml(entry.mode)} · ${escapeHtml(target || "not configured")}</div>
                </div>
                <span class="badge ${active ? "ok" : "idle"}">${active ? "ACTIVE" : "SAVED"}</span>
              </div>
              <p class="panel-copy">${escapeHtml(entry.notes || "No notes")}</p>
              <div class="button-row">
                <button class="secondary" data-action="select-profile" data-profile-id="${entry.id}">Use</button>
                <button class="ghost" data-action="delete-profile" data-profile-id="${entry.id}">Delete</button>
              </div>
            </article>
          `;
				})
				.join("")
		: `<div class="empty-state">No saved profiles yet. Create one to begin remote management.</div>`;

	const probeCards = state.probes.length
		? state.probes
				.map(
					(probe) => `
            <div class="status-card connection-card">
              <div class="status-row">
                <strong>${escapeHtml(probe.kind)}</strong>
                ${badge(probe)}
              </div>
              <div class="status-meta">${escapeHtml(probe.summary)}</div>
              <pre>${escapeHtml(probe.detail)}</pre>
            </div>
          `,
				)
				.join("")
		: `<div class="empty-state">Tap “Test connection” to probe Management API or Runtime API reachability.</div>`;

	const mode = profile?.mode ?? "management";

	app.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand"><span class="brand-dot"></span><span>Undefined Console</span></div>
        <p class="sidebar-copy">One shell for desktop and Android. Save remote profiles, test a management endpoint, and keep a runtime-only fallback profile around.</p>
        <div class="nav-stack">
          <button class="nav-button active">Connections</button>
          <button class="nav-button">Diagnostics</button>
          <button class="nav-button">About</button>
        </div>
      </aside>
      <main class="content">
        <section class="hero">
          <article class="hero-card">
            <p class="connection-meta">Cross-platform Tauri shell</p>
            <h1 class="hero-title">Remote-first management for Undefined.</h1>
            <p class="hero-subtitle">Use Management mode for configuration, logs, startup, and rescue flows. Keep Runtime-only profiles for direct probes and chat-facing inspection.</p>
            <div class="button-row">
              <button class="primary" data-action="test-connection">Test connection</button>
              <button class="secondary" data-action="seed-local">Seed local defaults</button>
            </div>
          </article>
          <div class="layout-grid">
            <section class="panel">
              <h2 class="section-title">Saved profiles</h2>
              <p class="panel-copy">Profiles are stored locally in the browser or WebView container.</p>
              <div class="connection-list">${connectionCards}</div>
            </section>
            <section class="panel">
              <h2 class="section-title">Profile editor</h2>
              <p class="panel-copy">Mobile uses the structured editor by default. Raw TOML editing belongs in the Management UI after you connect.</p>
              <form id="profile-form" class="form-grid">
                <div class="field">
                  <label for="profile-name">Display name</label>
                  <input id="profile-name" name="name" value="${escapeAttribute(profile?.name ?? "")}" required />
                </div>
                <div class="field">
                  <label for="profile-mode">Mode</label>
                  <select id="profile-mode" name="mode">
                    <option value="management" ${mode === "management" ? "selected" : ""}>Management</option>
                    <option value="runtime" ${mode === "runtime" ? "selected" : ""}>Runtime-only</option>
                  </select>
                </div>
                <div class="field full">
                  <label for="management-url">Management URL</label>
                  <input id="management-url" name="managementUrl" value="${escapeAttribute(profile?.managementUrl ?? "")}" placeholder="http://127.0.0.1:8787" />
                </div>
                <div class="field full">
                  <label for="runtime-url">Runtime URL</label>
                  <input id="runtime-url" name="runtimeUrl" value="${escapeAttribute(profile?.runtimeUrl ?? "")}" placeholder="http://127.0.0.1:8788" />
                </div>
                <div class="field full">
                  <label for="api-key">Runtime API key</label>
                  <input id="api-key" name="apiKey" value="${escapeAttribute(profile?.apiKey ?? "")}" placeholder="Used for runtime-only probing" />
                </div>
                <div class="field full">
                  <label for="notes">Notes</label>
                  <textarea id="notes" name="notes" placeholder="e.g. office staging, local laptop, Android fallback">${escapeHtml(profile?.notes ?? "")}</textarea>
                </div>
                <div class="field full">
                  <div class="button-row">
                    <button class="primary" type="submit">Save profile</button>
                    <button class="secondary" type="button" data-action="new-profile">New profile</button>
                  </div>
                  <div class="input-help">Management mode is the recommended path for config editing, log rescue, and startup flows.</div>
                </div>
              </form>
            </section>
          </div>
          <section class="panel">
            <h2 class="section-title">Diagnostics</h2>
            <p class="panel-copy">The shell probes a bootstrap endpoint first, then falls back to runtime health and OpenAPI discovery.</p>
            <div class="status-list">${probeCards}</div>
          </section>
        </section>
      </main>
      <nav class="mobile-tabbar">
        <button class="active">Profiles</button>
        <button>Probe</button>
        <button>About</button>
      </nav>
    </div>
  `;

	bindEvents();
};

const bindEvents = () => {
	document
		.querySelector<HTMLFormElement>("#profile-form")
		?.addEventListener("submit", (event) => {
			event.preventDefault();
			const form = new FormData(event.currentTarget as HTMLFormElement);

			const nextProfile: ConnectionProfile = {
				id: state.selectedId || crypto.randomUUID(),
				name: String(form.get("name") || "Untitled profile").trim(),
				mode:
					String(form.get("mode") || "management") === "runtime"
						? "runtime"
						: "management",
				managementUrl: normalizeUrl(String(form.get("managementUrl") || "")),
				runtimeUrl: normalizeUrl(String(form.get("runtimeUrl") || "")),
				apiKey: String(form.get("apiKey") || "").trim(),
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
			if (!profileId) {
				return;
			}
			state.selectedId = profileId;
			render();
		});
	}

	for (const button of document.querySelectorAll<HTMLElement>(
		"[data-action='delete-profile']",
	)) {
		button.addEventListener("click", () => {
			const profileId = button.dataset.profileId;
			if (!profileId) {
				return;
			}
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

	document
		.querySelector<HTMLElement>("[data-action='new-profile']")
		?.addEventListener("click", () => {
			const profile: ConnectionProfile = {
				id: crypto.randomUUID(),
				name: "New profile",
				mode: "management",
				managementUrl: "",
				runtimeUrl: "",
				apiKey: "",
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
				name: "Seeded local runtime",
				mode: "runtime",
				managementUrl: "http://127.0.0.1:8787",
				runtimeUrl: "http://127.0.0.1:8788",
				apiKey: "changeme",
				notes: "Use this to inspect a local Runtime API directly.",
			};
			state.profiles.unshift(profile);
			state.selectedId = profile.id;
			persistProfiles();
			render();
		});

	document
		.querySelector<HTMLElement>("[data-action='test-connection']")
		?.addEventListener("click", async () => {
			await runProbeSuite();
		});
};

const runProbeSuite = async () => {
	const profile = selectedProfile();
	if (!profile) {
		state.probes = [
			{
				kind: "Profile",
				status: "error",
				summary: "No active profile",
				detail: "Create or select a saved profile before probing.",
			},
		];
		render();
		return;
	}

	const probes: ProbeState[] = [];

	if (profile.managementUrl) {
		probes.push(await probeManagement(profile));
	}

	if (profile.runtimeUrl) {
		probes.push(await probeRuntime(profile));
	}

	if (probes.length === 0) {
		probes.push({
			kind: "Configuration",
			status: "error",
			summary: "No endpoints configured",
			detail: "Add a management URL or runtime URL before running probes.",
		});
	}

	state.probes = probes;
	render();
};

const probeManagement = async (
	profile: ConnectionProfile,
): Promise<ProbeState> => {
	const base = normalizeUrl(profile.managementUrl);
	const endpoints = [
		`${base}/api/v1/management/capabilities`,
		`${base}/api/session`,
		`${base}/`,
	];

	for (const endpoint of endpoints) {
		try {
			const response = await fetch(endpoint, { method: "GET" });
			const text = await response.text();
			return {
				kind: "Management API",
				status: response.ok ? "ok" : "error",
				summary: `${response.status} ${response.statusText}`,
				detail: `Endpoint: ${endpoint}\n\n${truncate(text)}`,
			};
		} catch (error) {
			if (endpoint === endpoints[endpoints.length - 1]) {
				return {
					kind: "Management API",
					status: "error",
					summary: "Endpoint unreachable",
					detail: `Tried ${endpoint}\n\n${String(error)}`,
				};
			}
		}
	}

	return {
		kind: "Management API",
		status: "error",
		summary: "Probe failed",
		detail: "Unknown failure while probing the management endpoint.",
	};
};

const probeRuntime = async (
	profile: ConnectionProfile,
): Promise<ProbeState> => {
	const base = normalizeUrl(profile.runtimeUrl);
	const headers = profile.apiKey
		? { "X-Undefined-API-Key": profile.apiKey }
		: undefined;

	try {
		const health = await fetch(`${base}/health`, { headers });
		const healthText = await health.text();
		const openapi = await fetch(`${base}/openapi.json`, { headers });
		const openapiText = await openapi.text();

		return {
			kind: "Runtime API",
			status: health.ok ? "ok" : "error",
			summary: `${health.status} ${health.statusText}`,
			detail: `Health: ${truncate(healthText)}\n\nOpenAPI: ${truncate(openapiText)}`,
		};
	} catch (error) {
		return {
			kind: "Runtime API",
			status: "error",
			summary: "Endpoint unreachable",
			detail: `Base URL: ${base}\n\n${String(error)}`,
		};
	}
};

const truncate = (value: string, maxLength = 1200): string =>
	value.length > maxLength ? `${value.slice(0, maxLength)}…` : value;

const escapeHtml = (value: string): string =>
	value
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#39;");

const escapeAttribute = (value: string): string =>
	escapeHtml(value).replaceAll("`", "&#96;");

render();
