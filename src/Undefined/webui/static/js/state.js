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
    lang: (initialState && initialState.lang) || getCookie("undefined_lang") || "zh",
    theme: "light",
    authenticated: false,
    usingDefaultPassword: !!(initialState && initialState.using_default_password),
    configExists: !!(initialState && initialState.config_exists),
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

const LOG_LEVELS = window.LogsController ? window.LogsController.LOG_LEVELS : ["all"];

function get(id) { return document.getElementById(id); }
function t(key) { return I18N[state.lang][key] || key; }

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
    if (parts.length === 2) return parts.pop().split(';').shift();
}

function setCookie(name, value, days = 30) {
    const d = new Date();
    d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
    let expires = "expires=" + d.toUTCString();
    document.cookie = name + "=" + value + ";" + expires + ";path=/;SameSite=Lax";
}
