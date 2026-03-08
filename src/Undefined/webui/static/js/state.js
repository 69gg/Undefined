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

const initialState = readJsonScript("initial-state", {});
const initialView = readJsonScript("initial-view", "landing");

const state = {
    lang:
        (initialState && initialState.lang) ||
        getCookie("undefined_lang") ||
        "zh",
    theme: "light",
    authenticated: false,
    authAccessToken: readStorage("undefined_auth_access_token"),
    authRefreshToken: readStorage("undefined_auth_refresh_token"),
    authAccessTokenExpiresAt:
        Number.parseInt(
            readStorage("undefined_auth_access_expires_at") || "0",
            10,
        ) || 0,
    authRefreshTimer: null,
    usingDefaultPassword: !!(
        initialState && initialState.using_default_password
    ),
    configExists: !!(initialState && initialState.config_exists),
    capabilities: null,
    tab: "overview",
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
