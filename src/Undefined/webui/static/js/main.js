/**
 * Undefined WebUI Main Script
 */

const I18N = {
    zh: {
        "landing.title": "Undefined 控制台",
        "landing.kicker": "WebUI",
        "landing.subtitle": "提供配置管理、日志追踪与运行控制的统一入口。",
        "landing.cta": "进入控制台",
        "landing.logs": "查看日志",
        "landing.about": "关于项目",
        "tabs.landing": "首页",
        "tabs.config": "配置修改",
        "tabs.logs": "运行日志",
        "tabs.about": "项目说明",
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
        "landing.logs": "View Logs",
        "landing.about": "About",
        "tabs.landing": "Landing",
        "tabs.config": "Configuration",
        "tabs.logs": "System Logs",
        "tabs.about": "About",
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
    lang: localStorage.getItem("lang") || "zh",
    authenticated: false,
    tab: "config",
    view: window.INITIAL_VIEW || "landing",
    config: {},
    bot: { running: false, pid: null, uptime: 0 },
    token: null,
    logTimer: null,
    statusTimer: null,
};

// Utils
function get(id) { return document.getElementById(id); }
function t(key) { return I18N[state.lang][key] || key; }

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
        localStorage.setItem("undefined_token", token);
    } else {
        localStorage.removeItem("undefined_token");
    }
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
        card.className = "card";
        card.innerHTML = `<h3 class="form-section-title">${section}</h3>`;

        for (const [key, val] of Object.entries(values)) {
            // Support one level deep (e.g. models.chat) if needed, 
            // but the backend summary merges them or keeps them as sub-objects.
            if (typeof val === "object" && !Array.isArray(val)) {
                // Nested Section
                const subTitle = document.createElement("div");
                subTitle.className = "muted-sm";
                subTitle.style.marginTop = "12px";
                subTitle.innerText = `[${section}.${key}]`;
                card.appendChild(subTitle);

                for (const [sk, sv] of Object.entries(val)) {
                    card.appendChild(createField(`${section}.${key}.${sk}`, sv));
                }
                continue;
            }
            card.appendChild(createField(`${section}.${key}`, val));
        }
        container.appendChild(card);
    }
}

function createField(path, val) {
    const group = document.createElement("div");
    group.className = "form-group";

    const label = document.createElement("label");
    label.className = "form-label";
    label.innerText = path.split(".").pop();
    group.appendChild(label);

    if (typeof val === "boolean") {
        const wrapper = document.createElement("label");
        wrapper.className = "toggle-wrapper";
        wrapper.innerHTML = `
            <input type="checkbox" class="toggle-input config-input" data-path="${path}" ${val ? "checked" : ""}>
            <span class="toggle-track"><span class="toggle-handle"></span></span>
        `;
        group.appendChild(wrapper);
    } else {
        const input = document.createElement("input");
        input.className = "form-control config-input";
        input.dataset.path = path;
        input.value = Array.isArray(val) ? val.join(", ") : val;
        group.appendChild(input);
    }
    return group;
}

async function saveConfig() {
    const btn = get("btnSaveConfig");
    const status = get("configStatus");
    btn.disabled = true;
    status.innerText = "...";

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
            status.innerText = "Saved successfully.";
            if (data.warning) status.innerText += ` Warning: ${data.warning}`;
            setTimeout(() => { status.innerText = ""; }, 3000);
        } else {
            status.innerText = "Error: " + data.error;
        }
    } catch (e) {
        status.innerText = e.message;
    } finally {
        btn.disabled = false;
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

    if (tab === "logs") {
        if (!state.logTimer) state.logTimer = setInterval(fetchLogs, 2000);
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
        localStorage.setItem("lang", state.lang);
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

    get("btnSaveConfig").onclick = saveConfig;
    get("btnRefreshLogs").onclick = fetchLogs;
    get("logoutBtn").onclick = () => {
        setToken(null);
        state.authenticated = false;
        state.view = "landing";
        refreshUI();
    };

    get("themeToggle").onclick = () => {
        const t = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", t);
        get("themeToggle").innerText = t === "dark" ? "Dark" : "Light";
    };

    // Initial data
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

