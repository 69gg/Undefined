function readJsonScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try {
        const text = (el.textContent || "").trim();
        if (!text) return fallback;
        return JSON.parse(text);
    } catch (e) {
        return fallback;
    }
}

function normalizeBootstrapAuthPayload(payload) {
    if (!payload || typeof payload !== "object") return null;
    const source =
        payload.tokens && typeof payload.tokens === "object"
            ? payload.tokens
            : payload;
    const accessToken = String(
        source.access_token || source.accessToken || "",
    ).trim();
    const refreshToken = String(
        source.refresh_token || source.refreshToken || "",
    ).trim();
    const accessTokenExpiresAt =
        Number.parseInt(
            String(
                source.access_token_expires_at ||
                    source.accessTokenExpiresAt ||
                    "0",
            ),
            10,
        ) || 0;
    if (!accessToken) return null;
    return { accessToken, refreshToken, accessTokenExpiresAt };
}

function decodeBase64UrlUtf8(value) {
    const normalized = String(value || "")
        .replace(/-/g, "+")
        .replace(/_/g, "/");
    const padded =
        normalized + "=".repeat((4 - (normalized.length % 4 || 4)) % 4);
    const binary = window.atob(padded);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
}

function readBootstrapAuthPayload() {
    const hash = String(window.location.hash || "").replace(/^#/, "");
    if (!hash) return null;
    const params = new URLSearchParams(hash);
    const raw = params.get("auth");
    if (!raw) return null;
    try {
        return normalizeBootstrapAuthPayload(
            JSON.parse(decodeBase64UrlUtf8(raw)),
        );
    } catch (_error) {
        return null;
    }
}

function persistBootstrapAuthPayload(payload) {
    if (!payload) return;
    try {
        if (payload.accessToken) {
            window.localStorage.setItem(
                "undefined_auth_access_token",
                payload.accessToken,
            );
        }
        if (payload.refreshToken) {
            window.localStorage.setItem(
                "undefined_auth_refresh_token",
                payload.refreshToken,
            );
        }
        if (payload.accessTokenExpiresAt) {
            window.localStorage.setItem(
                "undefined_auth_access_expires_at",
                String(payload.accessTokenExpiresAt),
            );
        }
    } catch (_error) {
        // ignore storage failures in hardened browsers/private mode
    }
}

function clearBootstrapAuthHash() {
    if (!String(window.location.hash || "").includes("auth=")) return;
    const nextUrl = `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(null, "", nextUrl);
}

const bootstrapAuth = readBootstrapAuthPayload();
if (bootstrapAuth) {
    persistBootstrapAuthPayload(bootstrapAuth);
    clearBootstrapAuthHash();
}

const initialState = readJsonScript("initial-state", {});
const initialView = readJsonScript("initial-view", "landing");

const state = {
    lang:
        (initialState && initialState.lang) ||
        getCookie("undefined_lang") ||
        "zh",
    theme: (initialState && initialState.theme) || "light",
    authenticated: false,
    launcherMode: !!(initialState && initialState.launcher_mode),
    returnTo: (initialState && initialState.return_to) || "",
    authAccessToken:
        (bootstrapAuth && bootstrapAuth.accessToken) ||
        readStorage("undefined_auth_access_token"),
    authRefreshToken:
        (bootstrapAuth && bootstrapAuth.refreshToken) ||
        readStorage("undefined_auth_refresh_token"),
    authAccessTokenExpiresAt:
        Number(
            (bootstrapAuth && bootstrapAuth.accessTokenExpiresAt) ||
                Number.parseInt(
                    readStorage("undefined_auth_access_expires_at") || "0",
                    10,
                ) ||
                0,
        ) || 0,
    authRefreshTimer: null,
    usingDefaultPassword: !!(
        initialState && initialState.using_default_password
    ),
    configExists: !!(initialState && initialState.config_exists),
    capabilities: null,
    tab: (initialState && initialState.initial_tab) || "overview",
    view: initialView || "landing",
    config: {},
    comments: {},
    configCollapsed: {},
    configSearch: "",
    configLoading: false,
    configLoaded: false,
    bot: { running: false, pid: null, uptime: 0 },
    logsRaw: "",
    logSearch: "",
    logLevel: "all",
    logLevelGte: false,
    logType: "bot",
    logFiles: {},
    logFile: "",
    logFileCurrent: "",
    logStreamEnabled: true,
    logsPaused: false,
    logAutoRefresh: true,
    logStream: null,
    logStreamFailed: false,
    logAtBottom: true,
    logScrollBound: false,
    logTimer: null,
    statusTimer: null,
    systemTimer: null,
    saveTimer: null,
    saveStatus: "idle",
    fetchBackoff: { status: 0, system: 0, logs: 0 },
    nextFetchAt: { status: 0, system: 0, logs: 0 },
};

const REFRESH_INTERVALS = {
    status: 3000,
    system: 1000,
    logs: 1000,
};

const THEME_COLORS = {
    light: "#f9f5f1",
    dark: "#0f1112",
};

const LOG_LEVELS = window.LogsController
    ? window.LogsController.LOG_LEVELS
    : ["all"];

function get(id) {
    return document.getElementById(id);
}
function t(key) {
    return I18N[state.lang][key] || key;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function setButtonLoading(button, loading) {
    if (!button) return;
    button.disabled = loading;
    button.classList.toggle("is-loading", loading);
    button.setAttribute("aria-busy", loading ? "true" : "false");
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
}

function setCookie(name, value, days = 30) {
    const d = new Date();
    d.setTime(d.getTime() + days * 24 * 60 * 60 * 1000);
    const expires = `expires=${d.toUTCString()}`;
    document.cookie = `${name}=${value};${expires};path=/;SameSite=Lax`;
}

function readStorage(key) {
    try {
        return window.localStorage.getItem(key) || "";
    } catch (_error) {
        return "";
    }
}

function writeStorage(key, value) {
    try {
        if (value === null || value === undefined || value === "") {
            window.localStorage.removeItem(key);
            return;
        }
        window.localStorage.setItem(key, String(value));
    } catch (_error) {
        // ignore storage failures in hardened browsers/private mode
    }
}

function clearStoredAuthTokens() {
    state.authAccessToken = "";
    state.authRefreshToken = "";
    state.authAccessTokenExpiresAt = 0;
    writeStorage("undefined_auth_access_token", "");
    writeStorage("undefined_auth_refresh_token", "");
    writeStorage("undefined_auth_access_expires_at", "");
    if (state.authRefreshTimer) {
        clearTimeout(state.authRefreshTimer);
        state.authRefreshTimer = null;
    }
}

function storeAuthTokens({
    accessToken = "",
    refreshToken = "",
    accessTokenExpiresAt = 0,
} = {}) {
    state.authAccessToken = accessToken || "";
    state.authRefreshToken = refreshToken || "";
    state.authAccessTokenExpiresAt = Number.isFinite(
        Number(accessTokenExpiresAt),
    )
        ? Number(accessTokenExpiresAt)
        : 0;
    writeStorage("undefined_auth_access_token", state.authAccessToken);
    writeStorage("undefined_auth_refresh_token", state.authRefreshToken);
    writeStorage(
        "undefined_auth_access_expires_at",
        state.authAccessTokenExpiresAt || "",
    );
}
