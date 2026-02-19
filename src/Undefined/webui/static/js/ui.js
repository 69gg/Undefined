function updateI18N() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
        el.innerText = t(el.getAttribute("data-i18n"));
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
        el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
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
    while (select.firstChild) select.removeChild(select.firstChild);
    LOG_LEVELS.forEach(level => {
        const option = document.createElement("option");
        option.value = level;
        option.textContent = t(`logs.level.${level}`);
        select.appendChild(option);
    });
    const valid = LOG_LEVELS.includes(current) ? current : "all";
    select.value = valid;
    state.logLevel = valid;
}

function updateLogPauseLabel() {
    const button = get("btnPauseLogs");
    if (!button) return;
    button.innerText = state.logsPaused ? t("logs.resume") : t("logs.pause");
}

function updateLogTabs() {
    document.querySelectorAll(".log-tab").forEach(tab => {
        tab.classList.toggle("active", tab.dataset.logType === state.logType);
    });
}

function updateLogFileSelect() {
    const select = get("logFileSelect");
    if (!select) return;
    const files = state.logFiles[state.logType] || [];
    select.disabled = files.length === 0;
    while (select.firstChild) select.removeChild(select.firstChild);
    files.forEach(file => {
        const option = document.createElement("option");
        option.value = file.name;
        let label = file.current ? t("logs.file.current") : t("logs.file.history");
        if (state.logType === "all") label = t("logs.file.other");
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
    if (state.logType === "all") {
        state.logStreamEnabled = false;
        return;
    }
    state.logStreamEnabled = !state.logFile || state.logFile === state.logFileCurrent;
}

function updateConfigStateLabel() {
    const stateEl = get("configState");
    if (!stateEl) return;
    const key = stateEl.dataset.i18nState;
    if (key) stateEl.innerText = t(key);
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

function updateAuthPanels() {
    const usingDefault = !!state.usingDefaultPassword;
    const showLanding = !state.authenticated && state.view === "landing";
    const showAppLogin = !state.authenticated && state.view === "app";

    const landingLogin = get("landingLoginBox");
    const landingReset = get("landingPasswordResetBox");
    if (landingLogin) landingLogin.style.display = showLanding && !usingDefault ? "block" : "none";
    if (landingReset) landingReset.style.display = showLanding && usingDefault ? "block" : "none";

    const appLogin = get("appLoginBox");
    const appReset = get("appPasswordResetBox");
    if (appLogin) appLogin.style.display = showAppLogin && !usingDefault ? "block" : "none";
    if (appReset) appReset.style.display = showAppLogin && usingDefault ? "block" : "none";
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
    const keyMap = { loading: "config.loading", error: "config.error", empty: "config.no_results" };
    const key = keyMap[mode] || "common.error";
    stateEl.dataset.i18nState = key;
    stateEl.innerText = t(key);
    stateEl.style.display = "block";
    grid.style.display = mode === "loading" || mode === "error" ? "none" : "block";
}
