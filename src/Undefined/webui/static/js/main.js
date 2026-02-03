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
        "auth.title": "解锁控制台",
        "auth.subtitle": "请输入 WebUI 密码以继续操作。",
        "auth.placeholder": "请输入 WebUI 密码",
        "auth.sign_in": "登 录",
        "auth.sign_out": "退出登录",
        "auth.default_password": "默认密码仍在使用，请尽快修改 webui.password 并重启 WebUI。",
        "config.title": "配置修改",
        "config.subtitle": "按分类逐项调整配置，保存后自动触发热更新。",
        "config.save": "保存更改",
        "config.reset": "重置更改",
        "logs.title": "运行日志",
        "logs.subtitle": "实时查看最后 200 行日志输出。",
        "logs.auto": "自动刷新",
        "logs.refresh": "刷新",
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
        "auth.title": "Unlock Console",
        "auth.subtitle": "Please enter your WebUI password.",
        "auth.placeholder": "WebUI password",
        "auth.sign_in": "Sign In",
        "auth.sign_out": "Sign Out",
        "auth.default_password": "Default password is in use. Please change webui.password and restart.",
        "config.title": "Configuration",
        "config.subtitle": "Adjust settings by category. Changes trigger hot reload.",
        "config.save": "Save Changes",
        "config.reset": "Revert Changes",
        "logs.title": "System Logs",
        "logs.subtitle": "Real-time view of the last 200 log lines.",
        "logs.auto": "Auto Refresh",
        "logs.refresh": "Refresh",
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
    authenticated: false,
    tab: "overview",
    view: window.INITIAL_VIEW || "landing",
    config: {},
    bot: { running: false, pid: null, uptime: 0 },
    token: null,
    logTimer: null,
    statusTimer: null,
    systemTimer: null,
    saveTimer: null,
};

// Utils
function get(id) { return document.getElementById(id); }
function t(key) { return I18N[state.lang][key] || key; }

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
    get("langToggle").innerText = state.lang === "zh" ? "English" : "中文";
}

function setToken(token) {
    state.token = token;
    if (token) {
        setCookie("undefined_webui_token", token);
    } else {
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

    const res = await fetch(path, { ...options, headers });
    if (res.status === 401) {
        state.authenticated = false;
        refreshUI();
        throw new Error("Unauthorized");
    }
    return res;
}

// Actions
async function login(pwd, statusId) {
    const s = get(statusId);
    s.innerText = "...";
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
        } else {
            s.innerText = data.error || "Login failed";
        }
    } catch (e) {
        s.innerText = e.message;
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
    try {
        const res = await api("/api/status");
        const data = await res.json();
        state.bot = data;
        updateBotUI();
    } catch (e) { }
}

function updateBotUI() {
    const badge = get("botStateBadge");
    const metaL = get("botStatusMetaLanding");
    const hintL = get("botHintLanding");

    if (state.bot.running) {
        badge.innerText = t("bot.status.running");
        badge.className = "badge success";
        metaL.innerText = `PID: ${state.bot.pid} | Uptime: ${Math.round(state.bot.uptime_seconds)}s`;
        hintL.innerText = "Bot is active and processing events.";
        get("botStartBtnLanding").disabled = true;
        get("botStopBtnLanding").disabled = false;
    } else {
        badge.innerText = t("bot.status.stopped");
        badge.className = "badge";
        metaL.innerText = "--";
        hintL.innerText = "Bot is currently offline.";
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
    const res = await api("/api/config/summary");
    const data = await res.json();
    state.config = data.data;
    buildConfigForm();
}

function buildConfigForm() {
    const container = get("formSections");
    container.innerHTML = "";

    // Sort sections by SECTION_ORDER logic (already handled by backend mostly, 
    // but here we render top level keys as cards)
    for (const [section, values] of Object.entries(state.config)) {
        if (typeof values !== "object" || Array.isArray(values)) continue;

        const card = document.createElement("div");
        card.className = "card config-card";

        const header = document.createElement("div");
        header.className = "config-card-header";
        header.innerHTML = `<h3 class="form-section-title">${section}</h3>`;
        card.appendChild(header);

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
}

function showSaveStatus(status, text) {
    const el = get("saveStatus");
    const txt = get("saveStatusText");
    if (status === "saving") {
        el.style.opacity = "1";
        el.classList.add("active");
        txt.innerText = text || "Saving...";
    } else if (status === "saved") {
        el.classList.remove("active");
        txt.innerText = text || "Saved";
        setTimeout(() => {
            if (!state.saveTimer) el.style.opacity = "0";
        }, 2000);
    } else if (status === "error") {
        el.classList.remove("active");
        txt.innerText = text || "Error";
        el.style.opacity = "1";
    }
}

function createField(path, val) {
    const group = document.createElement("div");
    group.className = "form-group";

    const label = document.createElement("label");
    label.className = "form-label";
    label.innerText = path.split(".").pop();
    group.appendChild(label);

    let input;
    if (typeof val === "boolean") {
        const wrapper = document.createElement("label");
        wrapper.className = "toggle-wrapper";
        wrapper.innerHTML = `
            <input type="checkbox" class="toggle-input config-input" data-path="${path}" ${val ? "checked" : ""}>
            <span class="toggle-track"><span class="toggle-handle"></span></span>
        `;
        group.appendChild(wrapper);
        input = wrapper.querySelector("input");
        input.onchange = () => autoSave();
    } else {
        input = document.createElement("input");
        input.className = "form-control config-input";
        input.dataset.path = path;
        input.value = Array.isArray(val) ? val.join(", ") : val;
        group.appendChild(input);
        input.oninput = () => {
            if (state.saveTimer) clearTimeout(state.saveTimer);
            showSaveStatus("saving", "Typing...");
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
            val = input.value;
            // Native conversion
            if (!isNaN(val) && val.trim() !== "") {
                val = val.includes(".") ? parseFloat(val) : parseInt(val);
            } else if (val.includes(",")) {
                val = val.split(",").map(s => s.trim());
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
                showToast(`Warning: ${data.warning}`, "warning", 5000);
            }
        } else {
            showSaveStatus("error", "Error saving");
            showToast(`Error: ${data.error}`, "error", 5000);
        }
    } catch (e) {
        showSaveStatus("error", "Network Error");
        showToast(`Error: ${e.message}`, "error", 5000);
    }
}

async function resetConfig() {
    if (!confirm("Are you sure you want to revert all local changes? This will reload the configuration from the server.")) return;
    try {
        await loadConfig();
        showToast("Configuration reloaded from server.", "info");
    } catch (e) {
        showToast("Failed to reload configuration.", "error");
    }
}

async function fetchLogs() {
    try {
        const res = await api("/api/logs?lines=200");
        const text = await res.text();
        const container = get("logContainer");
        const auto = get("logAutoScroll").checked;

        // simple ansi color
        const colored = text
            .replace(/\x1b\[31m/g, '<span class="ansi-red">')
            .replace(/\x1b\[32m/g, '<span class="ansi-green">')
            .replace(/\x1b\[33m/g, '<span class="ansi-yellow">')
            .replace(/\x1b\[34m/g, '<span class="ansi-blue">')
            .replace(/\x1b\[35m/g, '<span class="ansi-magenta">')
            .replace(/\x1b\[36m/g, '<span class="ansi-cyan">')
            .replace(/\x1b\[0m/g, '</span>');

        container.innerHTML = colored;
        if (auto) container.scrollTop = container.scrollHeight;
    } catch (e) { }
}

async function fetchSystemInfo() {
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
    } catch (e) { }
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
            loadConfig();
        } else {
            get("appLoginBox").style.display = "block";
            get("appContent").style.display = "none";
        }
    }

    if (window.INITIAL_STATE && window.INITIAL_STATE.version) {
        get("about-version-display").innerText = window.INITIAL_STATE.version;
    }
    if (window.INITIAL_STATE && window.INITIAL_STATE.license) {
        get("about-license-display").innerText = window.INITIAL_STATE.license;
    }

    get("landingLoginBox").style.display = (!state.authenticated && state.view === "landing") ? "block" : "none";
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
        if (!state.systemTimer) state.systemTimer = setInterval(fetchSystemInfo, 5000);
        fetchSystemInfo();
    } else {
        if (state.systemTimer) { clearInterval(state.systemTimer); state.systemTimer = null; }
    }

    if (tab === "logs") {
        if (!state.logTimer) state.logTimer = setInterval(fetchLogs, 1000);
        fetchLogs();
    } else {
        if (state.logTimer) { clearInterval(state.logTimer); state.logTimer = null; }
    }
}

// Init
async function init() {
    state.token = localStorage.getItem("undefined_token");

    // Bind Landing
    get("langToggle").onclick = () => {
        state.lang = state.lang === "zh" ? "en" : "zh";
        setCookie("undefined_lang", state.lang);
        updateI18N();
    };

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

    get("landingLoginBtn").onclick = () => login(get("landingPasswordInput").value, "landingLoginStatus");
    get("appLoginBtn").onclick = () => login(get("appPasswordInput").value, "appLoginStatus");

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
    });

    get("btnResetConfig").onclick = resetConfig;
    get("btnRefreshLogs").onclick = fetchLogs;
    get("btnRefreshOverview").onclick = fetchSystemInfo;
    get("logoutBtn").onclick = () => {
        setToken(null);
        state.authenticated = false;
        state.view = "landing";
        refreshUI();
    };
    get("mobileLogoutBtn").onclick = () => {
        setToken(null);
        state.authenticated = false;
        state.view = "landing";
        refreshUI();
    };

    get("themeToggle").onclick = () => {
        const t = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", t);
        setCookie("undefined_theme", t);
        get("themeToggle").innerText = t === "dark" ? "Dark" : "Light";
    };

    // Initial data
    state.token = getCookie("undefined_webui_token");
    if (window.INITIAL_STATE && window.INITIAL_STATE.theme) {
        document.documentElement.setAttribute("data-theme", window.INITIAL_STATE.theme);
        get("themeToggle").innerText = window.INITIAL_STATE.theme === "dark" ? "Dark" : "Light";
    }

    try {
        const session = await checkSession();
        state.authenticated = !!session.authenticated;
    } catch (e) {
        console.error("Session check failed", e);
        state.authenticated = false;
    }

    refreshUI();
    fetchStatus();
    state.statusTimer = setInterval(fetchStatus, 3000);
}

document.addEventListener("DOMContentLoaded", init);
