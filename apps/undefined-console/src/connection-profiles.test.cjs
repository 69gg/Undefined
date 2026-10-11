const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const ts = require("typescript");

const PROFILE_KEY = "undefined.console.profiles";
const source = readFileSync(join(__dirname, "main.ts"), "utf8");
const compiled = ts.transpileModule(source, {
	compilerOptions: {
		module: ts.ModuleKind.CommonJS,
		target: ts.ScriptTarget.ES2022,
	},
}).outputText;

// Execute the actual app and its form handlers. Storage, HTTP and navigation are
// isolated in memory; imports outside the two mocked Tauri modules are rejected.
function loadConsole(profiles, { native = false } = {}) {
	const storage = new Map();
	if (profiles !== undefined)
		storage.set(PROFILE_KEY, JSON.stringify(profiles));
	const calls = [];
	const navigations = [];
	const app = { innerHTML: "" };
	const form = {
		values: {},
		addEventListener(event, handler) {
			this[event] = handler;
		},
	};
	const document = {
		documentElement: { lang: "", dataset: {} },
		querySelector(selector) {
			if (selector === "#app") return app;
			if (selector === "#profile-form") return form;
			return null;
		},
		querySelectorAll: () => [],
	};
	const request = async (url, init = {}) => {
		// No branch invokes Node/global fetch or any real Runtime.
		calls.push({ url, ...init });
		return new Response(
			JSON.stringify({
				access_token: "FAKE-TOKEN",
				refresh_token: "FAKE-REFRESH",
			}),
			{ status: 200, headers: { "Content-Type": "application/json" } },
		);
	};
	const exports = {};
	const load = new Function(
		"require",
		"exports",
		"localStorage",
		"document",
		"window",
		"fetch",
		"FormData",
		`${compiled}\nreturn { state, openWebui, runProbes, buildManagementUrl, buildRuntimeUrl };`,
	);
	const consoleApp = load(
		(name) => {
			if (name === "@tauri-apps/api/core") return { isTauri: () => native };
			if (name === "@tauri-apps/plugin-http") return { fetch: request };
			if (name === "./style.css") return {};
			throw new Error(`Unexpected import: ${name}`);
		},
		exports,
		{
			getItem: (key) => storage.get(key) ?? null,
			setItem: (key, value) => storage.set(key, value),
		},
		document,
		{
			location: {
				href: "tauri://localhost/",
				assign: (url) => navigations.push(url),
			},
		},
		request,
		class FormData {
			constructor(currentForm) {
				this.values = currentForm.values;
			}
			get(key) {
				return this.values[key] ?? null;
			}
		},
	);
	return {
		...consoleApp,
		app,
		storage,
		calls,
		navigations,
		submit(values) {
			form.values = values;
			form.submit({ currentTarget: form, preventDefault() {} });
		},
	};
}

test("legacy HTTPS origins stay HTTPS through the actual password login and probes", async () => {
	const app = loadConsole(
		[
			{
				id: "tls",
				managementUrl: "https://secure.example:443",
				runtimeUrl: "https://secure.example:9443",
				password: "FAKE-PASSWORD",
			},
		],
		{ native: true },
	);
	const profile = app.state.profiles[0];
	assert.equal(profile.managementScheme, "https");
	assert.equal(profile.runtimeScheme, "https");
	assert.equal(profile.managementPort, "443");
	assert.equal(profile.runtimePort, "9443");
	await app.openWebui();
	assert.equal(
		app.calls[0].url,
		"https://secure.example:443/api/v1/management/auth/login",
	);
	assert.equal(app.calls[0].method, "POST");
	assert.equal(app.calls[0].body, '{"password":"FAKE-PASSWORD"}');
	assert.equal(new URL(app.navigations[0]).origin, "https://secure.example");
	await app.runProbes();
	assert.ok(app.calls.every((call) => new URL(call.url).protocol === "https:"));
	assert.ok(
		app.calls.some((call) => call.url === "https://secure.example:9443/health"),
	);
});

test("legacy IPv6 produces one pair of brackets and reaches login/navigation", async () => {
	const app = loadConsole([
		{
			id: "ipv6",
			managementUrl: "http://[::1]:8787",
			runtimeUrl: "https://[::1]:9443",
			password: "FAKE-PASSWORD",
		},
	]);
	const profile = app.state.profiles[0];
	assert.equal(profile.host, "::1");
	assert.equal(app.buildManagementUrl(profile), "http://[::1]:8787");
	assert.equal(app.buildRuntimeUrl(profile), "https://[::1]:9443");
	await app.openWebui();
	assert.equal(
		app.calls[0].url,
		"http://[::1]:8787/api/v1/management/auth/login",
	);
	assert.equal(new URL(app.navigations[0]).origin, "http://[::1]:8787");
});

test("the editor saves migrated protocol choices and reloads them without legacy URL fields", async () => {
	const app = loadConsole([
		{
			id: "migration",
			name: "TLS connection",
			managementUrl: "https://[2001:db8::1]:8443",
			runtimeUrl: "http://[2001:db8::1]:8788",
		},
	]);
	assert.match(
		app.app.innerHTML,
		/name="managementScheme"><option value="http">HTTP<\/option><option value="https" selected>/,
	);
	assert.match(
		app.app.innerHTML,
		/name="runtimeScheme"><option value="http" selected>/,
	);
	app.submit({
		name: "TLS connection",
		host: "[2001:db8::1]",
		managementScheme: "https",
		managementPort: "8443",
		runtimeScheme: "http",
		runtimePort: "8788",
	});
	const saved = JSON.parse(app.storage.get(PROFILE_KEY));
	assert.equal(saved[0].managementUrl, undefined);
	assert.equal(saved[0].runtimeUrl, undefined);
	const reloaded = loadConsole(saved);
	const profile = reloaded.state.profiles[0];
	assert.equal(
		reloaded.buildManagementUrl(profile),
		"https://[2001:db8::1]:8443",
	);
	assert.equal(reloaded.buildRuntimeUrl(profile), "http://[2001:db8::1]:8788");
	await reloaded.openWebui();
	assert.equal(
		new URL(reloaded.navigations[0]).origin,
		"https://[2001:db8::1]:8443",
	);
});

test("the editor can explicitly choose distinct protocols and persist a TLS Runtime", () => {
	const app = loadConsole();
	app.submit({
		name: "Mixed connection",
		host: "example.test",
		managementScheme: "http",
		managementPort: "8787",
		runtimeScheme: "https",
		runtimePort: "443",
	});
	const reloaded = loadConsole(JSON.parse(app.storage.get(PROFILE_KEY)));
	const profile = reloaded.state.profiles[0];
	assert.equal(
		reloaded.buildManagementUrl(profile),
		"http://example.test:8787",
	);
	assert.equal(
		new URL(reloaded.buildRuntimeUrl(profile)).origin,
		"https://example.test",
	);
});

test("existing host/port profiles without protocol fields keep their HTTP defaults", () => {
	const app = loadConsole([
		{
			id: "current",
			host: "localhost",
			managementPort: "8787",
			runtimePort: "8788",
		},
	]);
	const profile = app.state.profiles[0];
	assert.equal(app.buildManagementUrl(profile), "http://localhost:8787");
	assert.equal(app.buildRuntimeUrl(profile), "http://localhost:8788");
	const initial = loadConsole();
	assert.equal(
		initial.buildManagementUrl(initial.state.profiles[0]),
		"http://127.0.0.1:8787",
	);
});

test("both bare and already-bracketed current IPv6 hosts are valid after reload", () => {
	for (const host of ["::1", "[::1]"]) {
		const app = loadConsole([
			{ id: "current", host, managementPort: "8787", runtimePort: "8788" },
		]);
		const profile = app.state.profiles[0];
		assert.equal(app.buildManagementUrl(profile), "http://[::1]:8787");
		assert.equal(
			new URL(app.buildRuntimeUrl(profile)).origin,
			"http://[::1]:8788",
		);
	}
});
