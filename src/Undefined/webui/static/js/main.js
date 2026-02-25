function refreshUI() {
    updateI18N();
    get("view-landing").className = state.view === "landing" ? "full-view active" : "full-view";
    get("view-app").style.display = state.view === "app" ? "grid" : "none";

    if (state.view === "app") {
        if (state.authenticated) {
            get("appContent").style.display = "block";
            if (!state.configLoaded) loadConfig();
            if (
                state.tab === "runtime" &&
                window.RuntimeController &&
                typeof window.RuntimeController.onTabActivated === "function"
            ) {
                window.RuntimeController.onTabActivated("runtime");
            }
        } else {
            get("appContent").style.display = "none";
            state.configLoaded = false;
        }
    }

    if (initialState && initialState.version) get("about-version-display").innerText = initialState.version;
    if (initialState && initialState.license) get("about-license-display").innerText = initialState.license;

    updateAuthPanels();

    if (state.view !== "app" || !state.authenticated) {
        stopSystemTimer(); stopLogStream(); stopLogTimer();
    }
    if (state.view === "app" && state.tab === "logs" && state.authenticated) fetchLogFiles();
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
        if (!document.hidden) { startSystemTimer(); fetchSystemInfo(); }
    } else {
        stopSystemTimer();
    }

    if (tab === "logs") {
        if (!document.hidden) {
            fetchLogFiles();
            updateLogRefreshState();
            if (!state.logsPaused) fetchLogs(true);
        }
    } else {
        stopLogStream(); stopLogTimer();
    }

    if (window.RuntimeController && typeof window.RuntimeController.onTabActivated === "function") {
        window.RuntimeController.onTabActivated(tab);
    }
}

async function init() {
    if (window.RuntimeController && typeof window.RuntimeController.init === "function") {
        window.RuntimeController.init();
    }

    document.querySelectorAll('[data-action="toggle-lang"]').forEach(btn => {
        btn.addEventListener("click", () => {
            state.lang = state.lang === "zh" ? "en" : "zh";
            setCookie("undefined_lang", state.lang);
            updateI18N();
        });
    });

    document.querySelectorAll('[data-action="toggle-theme"]').forEach(btn => {
        btn.addEventListener("click", () => applyTheme(state.theme === "dark" ? "light" : "dark"));
    });

    document.querySelectorAll('[data-action="open-app"]').forEach(el => {
        el.onclick = () => { state.view = "app"; switchTab(el.getAttribute("data-tab")); refreshUI(); };
    });

    get("botStartBtnLanding").onclick = () => {
        if (!state.authenticated) { get("landingLoginStatus").innerText = t("auth.subtitle"); get("landingPasswordInput").focus(); return; }
        botAction("start");
    };
    get("botStopBtnLanding").onclick = () => {
        if (!state.authenticated) { get("landingLoginStatus").innerText = t("auth.subtitle"); get("landingPasswordInput").focus(); return; }
        botAction("stop");
    };

    get("landingLoginBtn").onclick = () => login(get("landingPasswordInput").value, "landingLoginStatus", "landingLoginBtn");
    get("appLoginBtn").onclick = () => login(get("appPasswordInput").value, "appLoginStatus", "appLoginBtn");

    const landingResetBtn = get("landingResetPasswordBtn");
    if (landingResetBtn) {
        landingResetBtn.onclick = () => changePassword("landingCurrentPasswordInput", "landingNewPasswordInput", "landingResetStatus", "landingResetPasswordBtn");
    }
    const appResetBtn = get("appResetPasswordBtn");
    if (appResetBtn) {
        appResetBtn.onclick = () => changePassword("appCurrentPasswordInput", "appNewPasswordInput", "appResetStatus", "appResetPasswordBtn");
    }

    const bindEnterLogin = (inputId, statusId, btnId) => {
        const el = get(inputId);
        if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") login(el.value, statusId, btnId); });
    };
    bindEnterLogin("landingPasswordInput", "landingLoginStatus", "landingLoginBtn");
    bindEnterLogin("appPasswordInput", "appLoginStatus", "appLoginBtn");

    const bindEnterReset = (currentId, newId, statusId, btnId) => {
        [get(currentId), get(newId)].forEach(el => {
            if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") changePassword(currentId, newId, statusId, btnId); });
        });
    };
    bindEnterReset("landingCurrentPasswordInput", "landingNewPasswordInput", "landingResetStatus", "landingResetPasswordBtn");
    bindEnterReset("appCurrentPasswordInput", "appNewPasswordInput", "appResetStatus", "appResetPasswordBtn");

    document.querySelectorAll(".nav-item").forEach(el => {
        el.addEventListener("click", () => {
            const v = el.getAttribute("data-view");
            const tab = el.getAttribute("data-tab");
            if (v === "landing") { state.view = "landing"; refreshUI(); }
            else if (tab) switchTab(tab);
        });
        el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.click(); } });
    });

    const resetBtn = get("btnResetConfig");
    if (resetBtn) resetBtn.onclick = resetConfig;

    const refreshLogsBtn = get("btnRefreshLogs");
    if (refreshLogsBtn) {
        refreshLogsBtn.onclick = async () => {
            state.logStreamFailed = false;
            setButtonLoading(refreshLogsBtn, true);
            try { await fetchLogs(true); } finally { setButtonLoading(refreshLogsBtn, false); }
        };
    }

    const refreshOverviewBtn = get("btnRefreshOverview");
    if (refreshOverviewBtn) {
        refreshOverviewBtn.onclick = async () => {
            setButtonLoading(refreshOverviewBtn, true);
            try { await fetchSystemInfo(); } finally { setButtonLoading(refreshOverviewBtn, false); }
        };
    }

    const updateRestartBtn = get("btnUpdateRestart");
    if (updateRestartBtn) updateRestartBtn.onclick = () => updateAndRestartWebui(updateRestartBtn);

    const pauseLogsBtn = get("btnPauseLogs");
    if (pauseLogsBtn) {
        pauseLogsBtn.onclick = () => {
            state.logsPaused = !state.logsPaused;
            pauseLogsBtn.innerText = state.logsPaused ? t("logs.resume") : t("logs.pause");
            renderLogs();
            updateLogRefreshState();
            if (!state.logsPaused) { state.logStreamFailed = false; fetchLogs(true); }
        };
    }

    document.querySelectorAll(".log-tab").forEach(tab => {
        tab.addEventListener("click", () => { setLogType(tab.dataset.logType || "bot"); fetchLogs(true); });
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
            if (state.logAutoRefresh) { state.logStreamFailed = false; if (!state.logsPaused) fetchLogs(true); }
            updateLogRefreshState();
        };
    }

    const logLevelFilter = get("logLevelFilter");
    if (logLevelFilter) {
        logLevelFilter.onchange = () => { state.logLevel = logLevelFilter.value || "all"; renderLogs(); };
    }

    const logLevelGteToggle = get("logLevelGteToggle");
    if (logLevelGteToggle) {
        state.logLevelGte = logLevelGteToggle.checked;
        logLevelGteToggle.onchange = () => { state.logLevelGte = logLevelGteToggle.checked; renderLogs(); };
    }

    const logSearchInput = get("logSearchInput");
    if (logSearchInput) {
        logSearchInput.addEventListener("input", () => { state.logSearch = logSearchInput.value || ""; renderLogs(); });
    }

    const logClearBtn = get("btnClearLogs");
    if (logClearBtn) logClearBtn.onclick = () => { state.logsRaw = ""; renderLogs(); showToast(t("logs.cleared"), "info"); };

    const logCopyBtn = get("btnCopyLogs");
    if (logCopyBtn) logCopyBtn.onclick = copyLogsToClipboard;

    const logDownloadBtn = get("btnDownloadLogs");
    if (logDownloadBtn) logDownloadBtn.onclick = downloadLogs;

    const logJumpBtn = get("btnJumpLogs");
    if (logJumpBtn) {
        logJumpBtn.onclick = () => {
            const container = get("logContainer");
            if (container) { container.scrollTop = container.scrollHeight; state.logAtBottom = true; updateLogJumpButton(); }
        };
    }

    const configSearchInput = get("configSearchInput");
    if (configSearchInput) {
        configSearchInput.addEventListener("input", () => { state.configSearch = configSearchInput.value || ""; applyConfigFilter(); });
    }

    const configSearchClear = get("configSearchClear");
    if (configSearchClear && configSearchInput) {
        configSearchClear.onclick = () => { configSearchInput.value = ""; state.configSearch = ""; applyConfigFilter(); configSearchInput.focus(); };
    }

    const expandAllBtn = get("btnExpandAll");
    if (expandAllBtn) expandAllBtn.onclick = () => setAllSectionsCollapsed(false);

    const collapseAllBtn = get("btnCollapseAll");
    if (collapseAllBtn) collapseAllBtn.onclick = () => setAllSectionsCollapsed(true);

    const logout = async () => {
        try { await api("/api/logout", { method: "POST" }); } catch (e) { }
        state.authenticated = false;
        state.view = "landing";
        refreshUI();
    };
    get("logoutBtn").onclick = logout;
    get("mobileLogoutBtn").onclick = logout;

    applyTheme(initialState && initialState.theme ? initialState.theme : "light");

    try {
        const session = await checkSession();
        state.authenticated = !!session.authenticated;
    } catch (e) {
        state.authenticated = false;
    }

    const shouldRedirectToConfig = !!(initialState && initialState.redirect_to_config);
    if (shouldRedirectToConfig) { state.view = "app"; switchTab("config"); }

    document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
            stopStatusTimer(); stopSystemTimer(); stopLogStream(); stopLogTimer(); return;
        }
        startStatusTimer();
        if (state.view === "app" && state.tab === "overview") { startSystemTimer(); fetchSystemInfo(); }
        if (state.view === "app" && state.tab === "logs") {
            updateLogRefreshState();
            if (!state.logsPaused) fetchLogs(true);
        }
    });

    refreshUI();
    if (shouldRedirectToConfig) showToast(t("config.bootstrap_created"), "info", 6500);
    bindLogScroll();
    fetchStatus();
    if (!document.hidden) startStatusTimer();
}

document.addEventListener("DOMContentLoaded", init);
