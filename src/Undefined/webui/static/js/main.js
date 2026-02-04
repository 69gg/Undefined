/**
 * Undefined WebUI Main Script
 */

const I18N = {
    zh: {
        "landing.title": "Undefined 控制台",
        "landing.kicker": "WebUI",
        "landing.subtitle": "提供配置管理、日志追踪与运行控制的统一入口。",
        "landing.cta": "进入控制台",
        "landing.config": "配置修改",
        "landing.logs": "查看日志",
        "landing.about": "关于项目",
        "theme.light": "浅色",
        "theme.dark": "深色",
        "common.loading": "加载中...",
        "common.error": "发生错误",
        "common.saved": "已保存",
        "common.warning": "警告",
        "tabs.landing": "首页",
        "tabs.overview": "运行概览",
        "tabs.config": "配置修改",
        "tabs.logs": "运行日志",
        "tabs.about": "项目说明",
        "overview.title": "运行概览",
        "overview.subtitle": "当前系统资源与运行环境快照。",
        "overview.refresh": "刷新",
        "overview.system": "系统信息",
        "overview.resources": "资源使用",
        "overview.runtime": "运行环境",
        "overview.cpu_model": "CPU 型号",
        "overview.cpu_usage": "CPU 占用率",
        "overview.memory": "内存容量",
        "overview.memory_usage": "内存占用率",
        "overview.system_version": "系统版本",
        "overview.system_arch": "系统架构",
        "overview.undefined_version": "Undefined 版本",
        "overview.python_version": "Python 版本",
        "overview.kernel": "内核版本",
        "bot.title": "机器人运行状态",
        "bot.start": "启动机器人",
        "bot.stop": "停止机器人",
        "bot.status.running": "运行中",
        "bot.status.stopped": "未启动",
        "bot.hint.running": "机器人正在运行并处理事件。",
        "bot.hint.stopped": "机器人当前离线。",
        "auth.title": "解锁控制台",
        "auth.subtitle": "请输入 WebUI 密码以继续操作。",
        "auth.placeholder": "请输入 WebUI 密码",
        "auth.sign_in": "登 录",
        "auth.sign_out": "退出登录",
        "auth.default_password": "默认密码仍在使用，请尽快修改 webui.password 并重启 WebUI。",
        "auth.signing_in": "登录中...",
        "auth.login_failed": "登录失败",
        "auth.unauthorized": "未登录或会话过期",
        "config.title": "配置修改",
        "config.subtitle": "按分类逐项调整配置，保存后自动触发热更新。",
        "config.save": "保存更改",
        "config.reset": "重置更改",
        "config.reset_confirm": "确定要撤销所有本地更改吗？这将从服务器重新加载配置。",
        "config.search_placeholder": "搜索配置...",
        "config.clear_search": "清除搜索",
        "config.expand_all": "全部展开",
        "config.collapse_all": "全部折叠",
        "config.expand_section": "展开",
        "config.collapse_section": "折叠",
        "config.loading": "正在加载配置...",
        "config.error": "配置加载失败，请重试。",
        "config.no_results": "未找到匹配项。",
        "config.typing": "输入中...",
        "config.saving": "保存中...",
        "config.saved": "已保存",
        "config.save_error": "保存失败",
        "config.save_network_error": "网络错误",
        "config.reload_success": "配置已从服务器重新加载。",
        "config.reload_error": "配置重载失败。",
        "logs.title": "运行日志",
        "logs.subtitle": "实时查看日志尾部输出。",
        "logs.auto": "自动刷新",
        "logs.refresh": "刷新",
        "logs.initializing": "正在连接日志...",
        "logs.search_placeholder": "搜索日志...",
        "logs.clear": "清空",
        "logs.copy": "复制",
        "logs.download": "下载",
        "logs.pause": "暂停",
        "logs.resume": "继续",
        "logs.jump_bottom": "回到底部",
        "logs.tab.bot": "Bot 日志",
        "logs.tab.webui": "WebUI 日志",
        "logs.file.current": "当前",
        "logs.file.history": "历史",
        "logs.empty": "暂无日志。",
        "logs.error": "日志加载失败。",
        "logs.unauthorized": "未登录，无法读取日志。",
        "logs.copied": "日志已复制。",
        "logs.download_ready": "日志已准备下载。",
        "logs.cleared": "日志已清空。",
        "logs.paused": "已暂停",
        "logs.filtered": "已过滤",
        "logs.level.all": "全部",
        "logs.level.info": "Info",
        "logs.level.warn": "Warn",
        "logs.level.error": "Error",
        "logs.level.debug": "Debug",
        "about.title": "项目信息",
        "about.subtitle": "关于 Undefined 项目的作者及许可协议。",
        "about.author": "作者",
        "about.author_name": "Null (pylindex@qq.com)",
        "about.version": "版本",
        "about.license": "许可协议",
        "about.license_name": "MIT License",
    },
    en: {
        "landing.title": "Undefined Console",
        "landing.kicker": "WebUI",
        "landing.subtitle": "A unified entry point for configuration, log tracking, and runtime control.",
        "landing.cta": "Enter Console",
        "landing.config": "Edit Config",
        "landing.logs": "View Logs",
        "landing.about": "About",
        "theme.light": "Light",
        "theme.dark": "Dark",
        "common.loading": "Loading...",
        "common.error": "An error occurred",
        "common.saved": "Saved",
        "common.warning": "Warning",
        "tabs.landing": "Landing",
        "tabs.overview": "Overview",
        "tabs.config": "Configuration",
        "tabs.logs": "System Logs",
        "tabs.about": "About",
        "overview.title": "Overview",
        "overview.subtitle": "System resources and runtime snapshot.",
        "overview.refresh": "Refresh",
        "overview.system": "System",
        "overview.resources": "Resources",
        "overview.runtime": "Runtime",
        "overview.cpu_model": "CPU Model",
        "overview.cpu_usage": "CPU Usage",
        "overview.memory": "Memory",
        "overview.memory_usage": "Memory Usage",
        "overview.system_version": "System Version",
        "overview.system_arch": "Architecture",
        "overview.undefined_version": "Undefined Version",
        "overview.python_version": "Python Version",
        "overview.kernel": "Kernel",
        "bot.title": "Bot Status",
        "bot.start": "Start Bot",
        "bot.stop": "Stop Bot",
        "bot.status.running": "Running",
        "bot.status.stopped": "Stopped",
        "bot.hint.running": "Bot is active and processing events.",
        "bot.hint.stopped": "Bot is currently offline.",
        "auth.title": "Unlock Console",
        "auth.subtitle": "Please enter your WebUI password.",
        "auth.placeholder": "WebUI password",
        "auth.sign_in": "Sign In",
        "auth.sign_out": "Sign Out",
        "auth.default_password": "Default password is in use. Please change webui.password and restart.",
        "auth.signing_in": "Signing in...",
        "auth.login_failed": "Login failed",
        "auth.unauthorized": "Unauthorized or session expired",
        "config.title": "Configuration",
        "config.subtitle": "Adjust settings by category. Changes trigger hot reload.",
        "config.save": "Save Changes",
        "config.reset": "Revert Changes",
        "config.reset_confirm": "Are you sure you want to revert all local changes? This will reload the configuration from the server.",
        "config.search_placeholder": "Search config...",
        "config.clear_search": "Clear search",
        "config.expand_all": "Expand all",
        "config.collapse_all": "Collapse all",
        "config.expand_section": "Expand",
        "config.collapse_section": "Collapse",
        "config.loading": "Loading configuration...",
        "config.error": "Failed to load configuration.",
        "config.no_results": "No matching results.",
        "config.typing": "Typing...",
        "config.saving": "Saving...",
        "config.saved": "Saved",
        "config.save_error": "Save failed",
        "config.save_network_error": "Network error",
        "config.reload_success": "Configuration reloaded from server.",
        "config.reload_error": "Failed to reload configuration.",
        "logs.title": "System Logs",
        "logs.subtitle": "Real-time view of recent log output.",
        "logs.auto": "Auto Refresh",
        "logs.refresh": "Refresh",
        "logs.initializing": "Initializing log connection...",
        "logs.search_placeholder": "Search logs...",
        "logs.clear": "Clear",
        "logs.copy": "Copy",
        "logs.download": "Download",
        "logs.pause": "Pause",
        "logs.resume": "Resume",
        "logs.jump_bottom": "Jump to bottom",
        "logs.tab.bot": "Bot Logs",
        "logs.tab.webui": "WebUI Logs",
        "logs.file.current": "Current",
        "logs.file.history": "History",
        "logs.empty": "No logs available.",
        "logs.error": "Failed to load logs.",
        "logs.unauthorized": "Unauthorized to access logs.",
        "logs.copied": "Logs copied.",
        "logs.download_ready": "Logs download ready.",
        "logs.cleared": "Logs cleared.",
        "logs.paused": "Paused",
        "logs.filtered": "Filtered",
        "logs.level.all": "All",
        "logs.level.info": "Info",
        "logs.level.warn": "Warn",
        "logs.level.error": "Error",
        "logs.level.debug": "Debug",
        "about.title": "About Project",
        "about.subtitle": "Information about authors and open source licenses.",
        "about.author": "Author",
        "about.author_name": "Null (pylindex@qq.com)",
        "about.version": "Version",
        "about.license": "License",
        "about.license_name": "MIT License",
    }
};

const state = {
    lang: (window.INITIAL_STATE && window.INITIAL_STATE.lang) || getCookie("undefined_lang") || "zh",
    theme: "light",
    authenticated: false,
    tab: "overview",
    view: window.INITIAL_VIEW || "landing",
    config: {},
    comments: {},
    configCollapsed: {},
    configSearch: "",
    configLoading: false,
    configLoaded: false,
    bot: { running: false, pid: null, uptime: 0 },
    token: null,
    logsRaw: "",
    logSearch: "",
    logLevel: "all",
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

const LOG_LEVELS = ["all", "error", "warn", "info", "debug"];

// Utils
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

function updateI18N() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
        const key = el.getAttribute("data-i18n");
        el.innerText = t(key);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        const key = el.getAttribute("data-i18n-placeholder");
        el.placeholder = t(key);
    });
    updateToggleLabels();
    updateCommentTexts();
    updateConfigSearchIndex();
    applyConfigFilter();
    updateSectionToggleLabels();
    updateLogPlaceholder();
    updateLogFilterLabels();
    updateLogPauseLabel();
    updateLogTabs();
    updateLogFileSelect();
    updateSaveStatusText();
    updateConfigStateLabel();
    renderLogs();
}

function updateToggleLabels() {
    const langLabel = state.lang === "zh" ? "English" : "中文";
    document.querySelectorAll('[data-action="toggle-lang"]').forEach(btn => {
        btn.innerText = langLabel;
    });
    const themeLabel = state.theme === "dark" ? t("theme.dark") : t("theme.light");
    document.querySelectorAll('[data-action="toggle-theme"]').forEach(btn => {
        btn.innerText = themeLabel;
    });
}

function updateLogPlaceholder() {
    const container = get("logContainer");
    if (!container) return;
    if (container.dataset.placeholder === "true") {
        container.innerText = t("logs.initializing");
    }
}

function updateLogFilterLabels() {
    const select = get("logLevelFilter");
    if (!select) return;
    const current = select.value || state.logLevel;
    while (select.firstChild) {
        select.removeChild(select.firstChild);
    }
    LOG_LEVELS.forEach(level => {
        const option = document.createElement("option");
        option.value = level;
        option.textContent = t(`logs.level.${level}`);
        select.appendChild(option);
    });
    select.value = current || "all";
    state.logLevel = select.value;
}

function updateLogPauseLabel() {
    const button = get("btnPauseLogs");
    if (!button) return;
    button.innerText = state.logsPaused ? t("logs.resume") : t("logs.pause");
}

function updateLogTabs() {
    document.querySelectorAll(".log-tab").forEach(tab => {
        const logType = tab.dataset.logType;
        tab.classList.toggle("active", logType === state.logType);
    });
}

function updateLogFileSelect() {
    const select = get("logFileSelect");
    if (!select) return;
    const files = state.logFiles[state.logType] || [];
    while (select.firstChild) {
        select.removeChild(select.firstChild);
    }
    files.forEach(file => {
        const option = document.createElement("option");
        option.value = file.name;
        const label = file.current ? t("logs.file.current") : t("logs.file.history");
        option.textContent = `${file.name} (${label})`;
        select.appendChild(option);
    });
    if (!state.logFile || !files.find(file => file.name === state.logFile)) {
        state.logFile = state.logFileCurrent || (files[0] && files[0].name) || "";
    }
    select.value = state.logFile;
    updateLogStreamEligibility();
}

function updateLogStreamEligibility() {
    state.logStreamEnabled = !state.logFile || state.logFile === state.logFileCurrent;
}

function updateConfigStateLabel() {
    const stateEl = get("configState");
    if (!stateEl) return;
    const key = stateEl.dataset.i18nState;
    if (key) {
        stateEl.innerText = t(key);
    }
}

function updateSaveStatusText() {
    const txt = get("saveStatusText");
    if (!txt) return;
    if (state.saveStatus === "saving") {
        txt.innerText = t("config.saving");
    } else if (state.saveStatus === "saved") {
        txt.innerText = t("config.saved");
    } else if (state.saveStatus === "error") {
        txt.innerText = t("config.save_error");
    } else {
        txt.innerText = t("config.saving");
    }
}

function updateSectionToggleLabels() {
    document.querySelectorAll(".config-card").forEach(card => {
        const section = card.dataset.section;
        const toggle = card.querySelector(".config-card-actions button");
        if (!toggle || !section) return;
        const collapsed = !!state.configCollapsed[section];
        toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
}

function updateThemeColor(theme) {
    const meta = document.getElementById("themeColorMeta");
    if (!meta) return;
    meta.setAttribute("content", THEME_COLORS[theme] || THEME_COLORS.light);
}

function applyTheme(theme) {
    const normalized = theme === "dark" ? "dark" : "light";
    state.theme = normalized;
    document.documentElement.setAttribute("data-theme", normalized);
    setCookie("undefined_theme", normalized);
    updateToggleLabels();
    updateThemeColor(normalized);
}

function setToken(token) {
    state.token = token;
    if (!token) {
        document.cookie = "undefined_webui_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
        document.cookie = "undefined_webui=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;";
    }
}

function showToast(message, type = "info", duration = 3000) {
    const container = get("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerText = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("removing");
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

async function api(path, options = {}) {
    const headers = options.headers || {};
    if (state.token) headers["X-Auth-Token"] = state.token;
    if (options.method === "POST" && options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }

    const res = await fetch(path, {
        ...options,
        headers,
        credentials: options.credentials || "same-origin",
    });
    if (res.status === 401) {
        state.authenticated = false;
        refreshUI();
        throw new Error("Unauthorized");
    }
    return res;
}

function setConfigState(mode) {
    const stateEl = get("configState");
    const grid = get("formSections");
    if (!stateEl || !grid) return;
    if (!mode) {
        stateEl.style.display = "none";
        stateEl.dataset.i18nState = "";
        grid.style.display = "block";
        return;
    }
    const keyMap = {
        loading: "config.loading",
        error: "config.error",
        empty: "config.no_results",
    };
    const key = keyMap[mode] || "common.error";
    stateEl.dataset.i18nState = key;
    stateEl.innerText = t(key);
    stateEl.style.display = "block";
    grid.style.display = mode === "loading" || mode === "error" ? "none" : "block";
}

function shouldFetch(kind) {
    return Date.now() >= (state.nextFetchAt[kind] || 0);
}

function recordFetchError(kind) {
    const current = state.fetchBackoff[kind] || 0;
    const next = Math.min(5, current + 1);
    state.fetchBackoff[kind] = next;
    const delay = Math.min(15000, 1000 * Math.pow(2, next));
    state.nextFetchAt[kind] = Date.now() + delay;
}

function recordFetchSuccess(kind) {
    state.fetchBackoff[kind] = 0;
    state.nextFetchAt[kind] = 0;
}

function startStatusTimer() {
    if (!state.statusTimer) {
        state.statusTimer = setInterval(fetchStatus, REFRESH_INTERVALS.status);
    }
}

function stopStatusTimer() {
    if (state.statusTimer) {
        clearInterval(state.statusTimer);
        state.statusTimer = null;
    }
}

function startSystemTimer() {
    if (!state.systemTimer) {
        state.systemTimer = setInterval(fetchSystemInfo, REFRESH_INTERVALS.system);
    }
}

function stopSystemTimer() {
    if (state.systemTimer) {
        clearInterval(state.systemTimer);
        state.systemTimer = null;
    }
}

function startLogTimer() {
    if (!state.logTimer) {
        state.logTimer = setInterval(fetchLogs, REFRESH_INTERVALS.logs);
    }
}

function stopLogTimer() {
    if (state.logTimer) {
        clearInterval(state.logTimer);
        state.logTimer = null;
    }
}

// Actions
async function login(pwd, statusId, buttonId) {
    const s = get(statusId);
    const button = buttonId ? get(buttonId) : null;
    s.innerText = t("auth.signing_in");
    setButtonLoading(button, true);
    try {
        const res = await api("/api/login", {
            method: "POST",
            body: JSON.stringify({ password: pwd })
        });
        const data = await res.json();
        if (data.success) {
            setToken(data.token);
            state.authenticated = true;
            await checkSession();
            refreshUI();
            s.innerText = "";
        } else {
            s.innerText = data.error || t("auth.login_failed");
        }
    } catch (e) {
        s.innerText = e.message || t("auth.login_failed");
    } finally {
        setButtonLoading(button, false);
    }
}

async function checkSession() {
    try {
        const res = await api("/api/session");
        const data = await res.json();
        state.authenticated = data.authenticated;
        get("warningBox").style.display = data.using_default_password ? "block" : "none";
        get("navFooter").innerText = data.summary;
        return data;
    } catch (e) {
        return { authenticated: false };
    }
}

async function fetchStatus() {
    if (!shouldFetch("status")) return;
    try {
        const res = await api("/api/status");
        const data = await res.json();
        state.bot = data;
        recordFetchSuccess("status");
        updateBotUI();
    } catch (e) {
        recordFetchError("status");
    }
}

function updateBotUI() {
    const badge = get("botStateBadge");
    const metaL = get("botStatusMetaLanding");
    const hintL = get("botHintLanding");

    if (state.bot.running) {
        badge.innerText = t("bot.status.running");
        badge.className = "badge success";
        metaL.innerText = `PID: ${state.bot.pid} | Uptime: ${Math.round(state.bot.uptime_seconds)}s`;
        hintL.innerText = t("bot.hint.running");
        get("botStartBtnLanding").disabled = true;
        get("botStopBtnLanding").disabled = false;
    } else {
        badge.innerText = t("bot.status.stopped");
        badge.className = "badge";
        metaL.innerText = "--";
        hintL.innerText = t("bot.hint.stopped");
        get("botStartBtnLanding").disabled = false;
        get("botStopBtnLanding").disabled = true;
    }
}

async function botAction(action) {
    try {
        await api(`/api/bot/${action}`, { method: "POST" });
        await fetchStatus();
    } catch (e) { }
}

async function loadConfig() {
    if (state.configLoading) return;
    state.configLoading = true;
    state.configLoaded = false;
    setConfigState("loading");
    try {
        const res = await api("/api/config/summary");
        const data = await res.json();
        state.config = data.data;
        state.comments = data.comments || {};
        state.configLoaded = true;
        buildConfigForm();
        setConfigState(null);
    } catch (e) {
        setConfigState("error");
        showToast(t("config.error"), "error", 5000);
    } finally {
        state.configLoading = false;
    }
}

function getComment(path) {
    const entry = state.comments && state.comments[path];
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[state.lang] || entry.en || entry.zh || "";
}

function updateCommentTexts() {
    document.querySelectorAll("[data-comment-path]").forEach(el => {
        const path = el.getAttribute("data-comment-path");
        if (!path) return;
        const text = getComment(path);
        el.innerText = text;
    });
}

function updateConfigSearchIndex() {
    document.querySelectorAll(".form-group").forEach(group => {
        const label = group.querySelector(".form-label");
        const hint = group.querySelector(".form-hint");
        const path = group.dataset.path || "";
        const searchText = `${path} ${label ? label.innerText : ""} ${hint ? hint.innerText : ""}`.toLowerCase();
        group.dataset.searchText = searchText;
    });
}

function buildConfigForm() {
    const container = get("formSections");
    if (!container) return;
    container.textContent = "";

    // Sort sections by SECTION_ORDER logic (already handled by backend mostly, 
    // but here we render top level keys as cards)
    for (const [section, values] of Object.entries(state.config)) {
        if (typeof values !== "object" || Array.isArray(values)) continue;

        const card = document.createElement("div");
        card.className = "card config-card";
        card.dataset.section = section;
        const collapsed = !!state.configCollapsed[section];
        card.classList.toggle("is-collapsed", collapsed);

        const header = document.createElement("div");
        header.className = "config-card-header";

        const title = document.createElement("h3");
        title.className = "form-section-title";
        title.textContent = section;
        header.appendChild(title);

        const actions = document.createElement("div");
        actions.className = "config-card-actions";

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "btn ghost btn-sm";
        toggle.dataset.section = section;
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
        toggle.addEventListener("click", () => toggleSection(section));
        actions.appendChild(toggle);

        header.appendChild(actions);
        card.appendChild(header);

        const sectionComment = getComment(section);
        if (sectionComment) {
            const hint = document.createElement("p");
            hint.className = "form-section-hint";
            hint.innerText = sectionComment;
            hint.dataset.commentPath = section;
            card.appendChild(hint);
        }

        const fieldGrid = document.createElement("div");
        fieldGrid.className = "form-fields";
        card.appendChild(fieldGrid);

        for (const [key, val] of Object.entries(values)) {
            // Support one level deep (e.g. models.chat) if needed, 
            // but the backend summary merges them or keeps them as sub-objects.
            if (typeof val === "object" && !Array.isArray(val)) {
                // Nested Section
                const subSection = document.createElement("div");
                subSection.className = "form-subsection";

                const subTitle = document.createElement("div");
                subTitle.className = "form-subtitle";
                subTitle.innerText = `[${section}.${key}]`;
                subSection.appendChild(subTitle);

                const subCommentKey = `${section}.${key}`;
                const subComment = getComment(subCommentKey);
                if (subComment) {
                    const subHint = document.createElement("div");
                    subHint.className = "form-subtitle-hint";
                    subHint.innerText = subComment;
                    subHint.dataset.commentPath = subCommentKey;
                    subSection.appendChild(subHint);
                }

                const subGrid = document.createElement("div");
                subGrid.className = "form-fields";
                for (const [sk, sv] of Object.entries(val)) {
                    subGrid.appendChild(createField(`${section}.${key}.${sk}`, sv));
                }
                subSection.appendChild(subGrid);
                fieldGrid.appendChild(subSection);
                continue;
            }
            fieldGrid.appendChild(createField(`${section}.${key}`, val));
        }
        container.appendChild(card);
    }

    updateConfigSearchIndex();
    applyConfigFilter();
}

function toggleSection(section) {
    state.configCollapsed[section] = !state.configCollapsed[section];
    document.querySelectorAll(".config-card").forEach(card => {
        if (card.dataset.section !== section) return;
        const collapsed = !!state.configCollapsed[section];
        card.classList.toggle("is-collapsed", collapsed);
        const toggle = card.querySelector(".config-card-actions button");
        if (toggle) {
            toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
            toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        }
    });
}

function setAllSectionsCollapsed(collapsed) {
    document.querySelectorAll(".config-card").forEach(card => {
        const section = card.dataset.section;
        if (!section) return;
        state.configCollapsed[section] = collapsed;
        card.classList.toggle("is-collapsed", collapsed);
        const toggle = card.querySelector(".config-card-actions button");
        if (toggle) {
            toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
            toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        }
    });
}

function applyConfigFilter() {
    if (!state.configLoaded) return;
    const query = state.configSearch.trim().toLowerCase();
    let matchCount = 0;
    document.querySelectorAll(".config-card").forEach(card => {
        let cardMatches = 0;
        card.querySelectorAll(".form-group").forEach(group => {
            const haystack = group.dataset.searchText || "";
            const isMatch = !query || haystack.includes(query);
            group.classList.toggle("is-hidden", !isMatch);
            group.classList.toggle("is-match", isMatch && query.length > 0);
            if (isMatch) cardMatches += 1;
        });
        card.querySelectorAll(".form-subsection").forEach(section => {
            const visible = section.querySelector(".form-group:not(.is-hidden)");
            section.style.display = visible ? "" : "none";
        });
        card.classList.toggle("force-open", query.length > 0);
        card.classList.toggle("is-hidden", query.length > 0 && cardMatches === 0);
        matchCount += cardMatches;
    });

    if (query.length > 0 && matchCount === 0) {
        setConfigState("empty");
    } else if (state.configLoaded) {
        setConfigState(null);
    }
}

function showSaveStatus(status, text) {
    const el = get("saveStatus");
    const txt = get("saveStatusText");
    state.saveStatus = status;
    if (status === "saving") {
        el.style.opacity = "1";
        el.classList.add("active");
        txt.innerText = text || t("config.saving");
    } else if (status === "saved") {
        el.classList.remove("active");
        txt.innerText = text || t("config.saved");
        setTimeout(() => {
            if (!state.saveTimer) {
                el.style.opacity = "0";
                state.saveStatus = "idle";
                updateSaveStatusText();
            }
        }, 2000);
    } else if (status === "error") {
        el.classList.remove("active");
        txt.innerText = text || t("config.save_error");
        el.style.opacity = "1";
    }
}

function isSensitiveKey(path) {
    return /(password|token|secret|api_key|apikey|access_key|private_key)/i.test(path);
}

function isLongText(value) {
    return typeof value === "string" && (value.length > 80 || value.includes("\n"));
}

function createField(path, val) {
    const group = document.createElement("div");
    group.className = "form-group";
    group.dataset.path = path;

    const label = document.createElement("label");
    label.className = "form-label";
    label.innerText = path.split(".").pop();
    group.appendChild(label);

    const comment = getComment(path);
    if (comment) {
        const hint = document.createElement("div");
        hint.className = "form-hint";
        hint.innerText = comment;
        hint.dataset.commentPath = path;
        group.appendChild(hint);
    }

    const searchText = `${path} ${comment || ""}`.toLowerCase();
    group.dataset.searchText = searchText;

    let input;
    if (typeof val === "boolean") {
        const wrapper = document.createElement("label");
        wrapper.className = "toggle-wrapper";
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.className = "toggle-input config-input";
        toggle.dataset.path = path;
        toggle.dataset.valueType = "boolean";
        toggle.checked = Boolean(val);
        const track = document.createElement("span");
        track.className = "toggle-track";
        const handle = document.createElement("span");
        handle.className = "toggle-handle";
        track.appendChild(handle);
        wrapper.appendChild(toggle);
        wrapper.appendChild(track);
        group.appendChild(wrapper);
        input = toggle;
        input.onchange = () => autoSave();
    } else {
        const isArray = Array.isArray(val);
        const isNumber = typeof val === "number";
        const isSecret = isSensitiveKey(path);

        if (isLongText(val)) {
            input = document.createElement("textarea");
            input.className = "form-control form-textarea config-input";
            input.value = val || "";
            input.dataset.valueType = "string";
        } else {
            input = document.createElement("input");
            input.className = "form-control config-input";
            if (isNumber) {
                input.type = "number";
                input.step = "any";
                input.value = String(val);
                input.dataset.valueType = "number";
            } else if (isArray) {
                input.type = "text";
                input.value = val.join(", ");
                input.dataset.valueType = "array";
                const arrayType = val.every(item => typeof item === "number") ? "number" : "string";
                input.dataset.arrayType = arrayType;
            } else {
                input.type = isSecret ? "password" : "text";
                input.value = val == null ? "" : String(val);
                input.dataset.valueType = "string";
                if (isSecret) {
                    input.setAttribute("autocomplete", "new-password");
                }
            }
        }

        input.dataset.path = path;
        group.appendChild(input);
        input.oninput = () => {
            if (state.saveTimer) clearTimeout(state.saveTimer);
            showSaveStatus("saving", t("config.typing"));
            state.saveTimer = setTimeout(() => {
                state.saveTimer = null;
                autoSave();
            }, 1000);
        };
    }
    return group;
}

async function autoSave() {
    showSaveStatus("saving");

    const patch = {};
    document.querySelectorAll(".config-input").forEach(input => {
        const path = input.dataset.path;
        let val;
        if (input.type === "checkbox") {
            val = input.checked;
        } else {
            const raw = input.value;
            const valueType = input.dataset.valueType || "string";
            if (valueType === "number") {
                const trimmed = raw.trim();
                if (!trimmed) {
                    val = "";
                } else {
                    val = trimmed.includes(".") ? parseFloat(trimmed) : parseInt(trimmed, 10);
                    if (Number.isNaN(val)) {
                        val = raw;
                    }
                }
            } else if (valueType === "array") {
                const items = raw.split(",").map(s => s.trim()).filter(Boolean);
                if (input.dataset.arrayType === "number") {
                    val = items.map(item => {
                        const num = Number(item);
                        return Number.isNaN(num) ? item : num;
                    });
                } else {
                    val = items;
                }
            } else {
                val = raw;
            }
        }
        patch[path] = val;
    });

    try {
        const res = await api("/api/patch", {
            method: "POST",
            body: JSON.stringify({ patch })
        });
        const data = await res.json();
        if (data.success) {
            showSaveStatus("saved");
            if (data.warning) {
                showToast(`${t("common.warning")}: ${data.warning}`, "warning", 5000);
            }
        } else {
            showSaveStatus("error", t("config.save_error"));
            showToast(`${t("common.error")}: ${data.error}`, "error", 5000);
        }
    } catch (e) {
        showSaveStatus("error", t("config.save_network_error"));
        showToast(`${t("common.error")}: ${e.message}`, "error", 5000);
    }
}

async function resetConfig() {
    if (!confirm(t("config.reset_confirm"))) return;
    try {
        await loadConfig();
        showToast(t("config.reload_success"), "info");
    } catch (e) {
        showToast(t("config.reload_error"), "error");
    }
}

async function fetchLogs(force = false) {
    if (!force && !shouldFetch("logs")) return;
    const container = get("logContainer");
    if (container && !state.logsRaw) {
        container.dataset.placeholder = "true";
        container.innerText = t("logs.initializing");
    }
    try {
        const params = new URLSearchParams({
            lines: "200",
            type: state.logType,
        });
        if (state.logFile) {
            params.set("file", state.logFile);
        }
        const res = await api(`/api/logs?${params.toString()}`);
        const text = await res.text();
        state.logsRaw = text || "";
        recordFetchSuccess("logs");
        renderLogs();
    } catch (e) {
        recordFetchError("logs");
        if (!container) return;
        container.dataset.placeholder = "true";
        container.innerText = e.message === "Unauthorized" ? t("logs.unauthorized") : t("logs.error");
        updateLogMeta(0, 0);
    }
}

function parseLogLevel(line) {
    const lowered = line.toLowerCase();
    if (/(\berror\b|\bfatal\b|\bexception\b)/i.test(lowered)) return "error";
    if (/(\bwarn\b|\bwarning\b)/i.test(lowered)) return "warn";
    if (/(\bdebug\b|\btrace\b)/i.test(lowered)) return "debug";
    if (/(\binfo\b)/i.test(lowered)) return "info";
    return "all";
}

function filterLogLines(raw) {
    const lines = raw.split(/\r?\n/);
    const level = state.logLevel;
    const query = state.logSearch.trim().toLowerCase();
    const filtered = lines.filter(line => {
        if (level !== "all" && parseLogLevel(line) !== level) return false;
        if (query && !line.toLowerCase().includes(query)) return false;
        return true;
    });
    return {
        filtered,
        total: lines.filter(line => line.length > 0).length,
        matched: filtered.filter(line => line.length > 0).length,
    };
}

function formatLogText(text) {
    if (!text) return "";
    let escaped = escapeHtml(text);
    const query = state.logSearch.trim();
    if (query) {
        const regex = new RegExp(escapeRegExp(query), "gi");
        escaped = escaped.replace(regex, '<mark class="log-highlight">$&</mark>');
    }
    escaped = escaped.replace(
        /(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)/g,
        '<span class="log-timestamp">$1</span>'
    );
    return escaped
        .replace(/\x1b\[31m/g, '<span class="ansi-red">')
        .replace(/\x1b\[32m/g, '<span class="ansi-green">')
        .replace(/\x1b\[33m/g, '<span class="ansi-yellow">')
        .replace(/\x1b\[34m/g, '<span class="ansi-blue">')
        .replace(/\x1b\[35m/g, '<span class="ansi-magenta">')
        .replace(/\x1b\[36m/g, '<span class="ansi-cyan">')
        .replace(/\x1b\[0m/g, '</span>');
}

function renderLogs() {
    const container = get("logContainer");
    if (!container) return;
    if (!state.logsRaw) {
        container.dataset.placeholder = "true";
        container.innerText = t("logs.empty");
        state.logAtBottom = true;
        updateLogJumpButton();
        updateLogMeta(0, 0);
        return;
    }

    const { filtered, total, matched } = filterLogLines(state.logsRaw);
    if (filtered.length === 0) {
        container.dataset.placeholder = "true";
        container.innerText = t("logs.empty");
        state.logAtBottom = true;
        updateLogJumpButton();
        updateLogMeta(total, 0);
        return;
    }

    const formatted = formatLogText(filtered.join("\n"));
    container.innerHTML = formatted;
    container.dataset.placeholder = "false";
    if (state.logAutoRefresh && state.logAtBottom) {
        container.scrollTop = container.scrollHeight;
    }
    updateLogJumpButton();
    updateLogMeta(total, matched);
}

function updateLogMeta(total, matched) {
    const meta = get("logMeta");
    if (!meta) return;
    const parts = [];
    if (state.logsPaused) {
        parts.push(t("logs.paused"));
    }
    if (state.logLevel !== "all" || state.logSearch.trim()) {
        const stats = total > 0 ? `${matched}/${total}` : "0/0";
        parts.push(`${t("logs.filtered")}: ${stats}`);
    }
    meta.innerText = parts.join(" | ");
}

function updateLogJumpButton() {
    const button = get("btnJumpLogs");
    if (!button) return;
    if (state.logAtBottom) {
        button.style.visibility = "hidden";
        button.style.pointerEvents = "none";
    } else {
        button.style.visibility = "visible";
        button.style.pointerEvents = "auto";
    }
}

function bindLogScroll() {
    if (state.logScrollBound) return;
    const container = get("logContainer");
    if (!container) return;
    container.addEventListener("scroll", () => {
        const threshold = 24;
        state.logAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
        updateLogJumpButton();
    });
    state.logScrollBound = true;
    updateLogJumpButton();
}

function startLogStream() {
    if (state.logStream || state.logStreamFailed || !window.EventSource) return false;
    if (!state.logStreamEnabled) return false;
    state.logStreamFailed = false;
    const params = new URLSearchParams({
        lines: "200",
        type: state.logType,
    });
    const stream = new EventSource(`/api/logs/stream?${params.toString()}`);
    state.logStream = stream;

    stream.onmessage = (event) => {
        state.logsRaw = event.data || "";
        recordFetchSuccess("logs");
        renderLogs();
    };

    stream.onerror = () => {
        state.logStreamFailed = true;
        stopLogStream();
        if (state.logAutoRefresh && !state.logsPaused) {
            startLogTimer();
        }
    };

    return true;
}

function stopLogStream() {
    if (state.logStream) {
        state.logStream.close();
        state.logStream = null;
    }
}

function updateLogRefreshState() {
    if (state.view !== "app" || state.tab !== "logs" || document.hidden || !state.authenticated) {
        stopLogStream();
        stopLogTimer();
        return;
    }
    if (state.logsPaused || !state.logAutoRefresh) {
        stopLogStream();
        stopLogTimer();
        return;
    }
    if (!state.logStreamEnabled) {
        stopLogStream();
        startLogTimer();
        return;
    }
    if (startLogStream()) {
        stopLogTimer();
        return;
    }
    startLogTimer();
}

async function copyLogsToClipboard() {
    const text = state.logsRaw || "";
    if (!text) {
        showToast(t("logs.empty"), "info");
        return;
    }
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            document.execCommand("copy");
            textarea.remove();
        }
        showToast(t("logs.copied"), "success");
    } catch (e) {
        showToast(`${t("common.error")}: ${e.message}`, "error");
    }
}

async function fetchLogFiles(force = false) {
    if (state.logFiles[state.logType] && !force) {
        updateLogFileSelect();
        return;
    }
    try {
        const res = await api(`/api/logs/files?type=${state.logType}`);
        const data = await res.json();
        state.logFiles[state.logType] = data.files || [];
        state.logFileCurrent = data.current || "";
        updateLogFileSelect();
    } catch (e) {
        state.logFiles[state.logType] = [];
    }
}

function setLogType(type) {
    if (state.logType === type) return;
    state.logType = type;
    state.logFile = "";
    state.logsRaw = "";
    state.logStreamFailed = false;
    updateLogTabs();
    fetchLogFiles(true);
    renderLogs();
    updateLogRefreshState();
}

function downloadLogs() {
    const text = state.logsRaw || "";
    if (!text) {
        showToast(t("logs.empty"), "info");
        return;
    }
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `undefined-logs-${new Date().toISOString().replace(/[:.]/g, "-")}.log`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast(t("logs.download_ready"), "info");
}

async function fetchSystemInfo() {
    if (!shouldFetch("system")) return;
    try {
        const res = await api("/api/system");
        const data = await res.json();
        const cpuUsage = data.cpu_usage_percent ?? 0;
        const memUsage = data.memory_usage_percent ?? 0;

        get("systemCpuModel").innerText = data.cpu_model || "--";
        get("systemCpuUsage").innerText = data.cpu_usage_percent != null ? `${cpuUsage}%` : "--";
        get("systemMemory").innerText =
            data.memory_total_gb != null && data.memory_used_gb != null
                ? `${data.memory_used_gb} GB / ${data.memory_total_gb} GB`
                : "--";
        get("systemMemoryUsage").innerText = data.memory_usage_percent != null ? `${memUsage}%` : "--";
        get("systemVersion").innerText = data.system_version || "--";
        get("systemArch").innerText = data.system_arch || "--";
        get("systemKernel").innerText = data.system_release || "--";
        get("systemPythonVersion").innerText = data.python_version || "--";
        get("systemUndefinedVersion").innerText = data.undefined_version || "--";

        const cpuBar = get("systemCpuBar");
        const memBar = get("systemMemoryBar");
        cpuBar.style.width = `${Math.min(100, Math.max(0, cpuUsage))}%`;
        memBar.style.width = `${Math.min(100, Math.max(0, memUsage))}%`;
        recordFetchSuccess("system");
    } catch (e) {
        recordFetchError("system");
    }
}

// UI Controllers
function refreshUI() {
    updateI18N();
    get("view-landing").className = state.view === "landing" ? "full-view active" : "full-view";
    get("view-app").style.display = state.view === "app" ? "grid" : "none";

    if (state.view === "app") {
        if (state.authenticated) {
            get("appLoginBox").style.display = "none";
            get("appContent").style.display = "block";
            if (!state.configLoaded) {
                loadConfig();
            }
        } else {
            get("appLoginBox").style.display = "block";
            get("appContent").style.display = "none";
            state.configLoaded = false;
        }
    }

    if (window.INITIAL_STATE && window.INITIAL_STATE.version) {
        get("about-version-display").innerText = window.INITIAL_STATE.version;
    }
    if (window.INITIAL_STATE && window.INITIAL_STATE.license) {
        get("about-license-display").innerText = window.INITIAL_STATE.license;
    }

    get("landingLoginBox").style.display = (!state.authenticated && state.view === "landing") ? "block" : "none";

    if (state.view !== "app" || !state.authenticated) {
        stopSystemTimer();
        stopLogStream();
        stopLogTimer();
    }

    if (state.view === "app" && state.tab === "logs" && state.authenticated) {
        fetchLogFiles();
    }

    updateLogRefreshState();
}

function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".nav-item").forEach(el => {
        el.classList.toggle("active", el.getAttribute("data-tab") === tab);
    });
    document.querySelectorAll(".tab-content").forEach(el => {
        el.classList.toggle("active", el.id === `tab-${tab}`);
    });

    if (tab === "overview") {
        if (!document.hidden) {
            startSystemTimer();
            fetchSystemInfo();
        }
    } else {
        stopSystemTimer();
    }

    if (tab === "logs") {
        if (!document.hidden) {
            fetchLogFiles();
            updateLogRefreshState();
            if (!state.logsPaused) {
                fetchLogs(true);
            }
        }
    } else {
        stopLogStream();
        stopLogTimer();
    }
}

// Init
async function init() {
    // Bind Landing
    document.querySelectorAll('[data-action="toggle-lang"]').forEach(btn => {
        btn.addEventListener("click", () => {
            state.lang = state.lang === "zh" ? "en" : "zh";
            setCookie("undefined_lang", state.lang);
            updateI18N();
        });
    });

    document.querySelectorAll('[data-action="toggle-theme"]').forEach(btn => {
        btn.addEventListener("click", () => {
            const next = state.theme === "dark" ? "light" : "dark";
            applyTheme(next);
        });
    });

    document.querySelectorAll('[data-action="open-app"]').forEach(el => {
        el.onclick = () => {
            state.view = "app";
            switchTab(el.getAttribute("data-tab"));
            refreshUI();
        };
    });

    get("botStartBtnLanding").onclick = () => {
        if (!state.authenticated) {
            get("landingLoginStatus").innerText = t("auth.subtitle");
            get("landingPasswordInput").focus();
            return;
        }
        botAction("start");
    };
    get("botStopBtnLanding").onclick = () => {
        if (!state.authenticated) {
            get("landingLoginStatus").innerText = t("auth.subtitle");
            get("landingPasswordInput").focus();
            return;
        }
        botAction("stop");
    };

    get("landingLoginBtn").onclick = () =>
        login(get("landingPasswordInput").value, "landingLoginStatus", "landingLoginBtn");
    get("appLoginBtn").onclick = () =>
        login(get("appPasswordInput").value, "appLoginStatus", "appLoginBtn");

    get("landingPasswordInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            login(get("landingPasswordInput").value, "landingLoginStatus", "landingLoginBtn");
        }
    });
    get("appPasswordInput").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            login(get("appPasswordInput").value, "appLoginStatus", "appLoginBtn");
        }
    });

    // Bind App
    document.querySelectorAll(".nav-item").forEach(el => {
        el.addEventListener("click", () => {
            const v = el.getAttribute("data-view");
            const tab = el.getAttribute("data-tab");
            if (v === "landing") {
                state.view = "landing";
                refreshUI();
            } else if (tab) {
                switchTab(tab);
            }
        });
        el.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                el.click();
            }
        });
    });

    const resetBtn = get("btnResetConfig");
    if (resetBtn) resetBtn.onclick = resetConfig;

    const refreshLogsBtn = get("btnRefreshLogs");
    if (refreshLogsBtn) {
        refreshLogsBtn.onclick = async () => {
            state.logStreamFailed = false;
            setButtonLoading(refreshLogsBtn, true);
            try {
                await fetchLogs(true);
            } finally {
                setButtonLoading(refreshLogsBtn, false);
            }
        };
    }

    const refreshOverviewBtn = get("btnRefreshOverview");
    if (refreshOverviewBtn) {
        refreshOverviewBtn.onclick = async () => {
            setButtonLoading(refreshOverviewBtn, true);
            try {
                await fetchSystemInfo();
            } finally {
                setButtonLoading(refreshOverviewBtn, false);
            }
        };
    }

    const pauseLogsBtn = get("btnPauseLogs");
    if (pauseLogsBtn) {
        pauseLogsBtn.onclick = () => {
            state.logsPaused = !state.logsPaused;
            pauseLogsBtn.innerText = state.logsPaused ? t("logs.resume") : t("logs.pause");
            renderLogs();
            updateLogRefreshState();
            if (!state.logsPaused) {
                state.logStreamFailed = false;
                fetchLogs(true);
            }
        };
    }

    document.querySelectorAll(".log-tab").forEach(tab => {
        tab.addEventListener("click", () => {
            const logType = tab.dataset.logType || "bot";
            setLogType(logType);
            fetchLogs(true);
        });
    });

    const logFileSelect = get("logFileSelect");
    if (logFileSelect) {
        logFileSelect.addEventListener("change", () => {
            state.logFile = logFileSelect.value;
            updateLogStreamEligibility();
            updateLogRefreshState();
            fetchLogs(true);
        });
    }

    const logAutoRefresh = get("logAutoScroll");
    if (logAutoRefresh) {
        state.logAutoRefresh = logAutoRefresh.checked;
        logAutoRefresh.onchange = () => {
            state.logAutoRefresh = logAutoRefresh.checked;
            if (state.logAutoRefresh) {
                state.logStreamFailed = false;
                if (!state.logsPaused) {
                    fetchLogs(true);
                }
            }
            updateLogRefreshState();
        };
    }

    const logLevelFilter = get("logLevelFilter");
    if (logLevelFilter) {
        logLevelFilter.onchange = () => {
            state.logLevel = logLevelFilter.value || "all";
            renderLogs();
        };
    }

    const logSearchInput = get("logSearchInput");
    if (logSearchInput) {
        logSearchInput.addEventListener("input", () => {
            state.logSearch = logSearchInput.value || "";
            renderLogs();
        });
    }

    const logClearBtn = get("btnClearLogs");
    if (logClearBtn) {
        logClearBtn.onclick = () => {
            state.logsRaw = "";
            renderLogs();
            showToast(t("logs.cleared"), "info");
        };
    }

    const logCopyBtn = get("btnCopyLogs");
    if (logCopyBtn) {
        logCopyBtn.onclick = copyLogsToClipboard;
    }

    const logDownloadBtn = get("btnDownloadLogs");
    if (logDownloadBtn) {
        logDownloadBtn.onclick = downloadLogs;
    }

    const logJumpBtn = get("btnJumpLogs");
    if (logJumpBtn) {
        logJumpBtn.onclick = () => {
            const container = get("logContainer");
            if (container) {
                container.scrollTop = container.scrollHeight;
                state.logAtBottom = true;
                updateLogJumpButton();
            }
        };
    }

    const configSearchInput = get("configSearchInput");
    if (configSearchInput) {
        configSearchInput.addEventListener("input", () => {
            state.configSearch = configSearchInput.value || "";
            applyConfigFilter();
        });
    }

    const configSearchClear = get("configSearchClear");
    if (configSearchClear && configSearchInput) {
        configSearchClear.onclick = () => {
            configSearchInput.value = "";
            state.configSearch = "";
            applyConfigFilter();
            configSearchInput.focus();
        };
    }

    const expandAllBtn = get("btnExpandAll");
    if (expandAllBtn) {
        expandAllBtn.onclick = () => setAllSectionsCollapsed(false);
    }

    const collapseAllBtn = get("btnCollapseAll");
    if (collapseAllBtn) {
        collapseAllBtn.onclick = () => setAllSectionsCollapsed(true);
    }
    const logout = async () => {
        try {
            await api("/api/logout", { method: "POST" });
        } catch (e) {
            // ignore
        }
        setToken(null);
        state.authenticated = false;
        state.view = "landing";
        refreshUI();
    };

    get("logoutBtn").onclick = logout;
    get("mobileLogoutBtn").onclick = logout;

    // Initial data
    state.token = getCookie("undefined_webui_token");
    if (window.INITIAL_STATE && window.INITIAL_STATE.theme) {
        applyTheme(window.INITIAL_STATE.theme);
    } else {
        applyTheme("light");
    }

    try {
        const session = await checkSession();
        state.authenticated = !!session.authenticated;
    } catch (e) {
        console.error("Session check failed", e);
        state.authenticated = false;
    }

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopStatusTimer();
            stopSystemTimer();
            stopLogStream();
            stopLogTimer();
            return;
        }

        startStatusTimer();
        if (state.view === "app" && state.tab === "overview") {
            startSystemTimer();
            fetchSystemInfo();
        }
        if (state.view === "app" && state.tab === "logs") {
            updateLogRefreshState();
            if (!state.logsPaused) {
                fetchLogs(true);
            }
        }
    });

    refreshUI();
    bindLogScroll();
    fetchStatus();
    if (!document.hidden) {
        startStatusTimer();
    }
}

document.addEventListener("DOMContentLoaded", init);
