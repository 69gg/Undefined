function refreshUI() {
    updateI18N();
    get("view-landing").className =
        state.view === "landing" ? "full-view active" : "full-view";
    get("view-app").style.display = state.view === "app" ? "grid" : "none";

    if (state.view === "app") {
        if (state.authenticated) {
            get("appContent").style.display = "block";
            if (!state.configLoaded) loadConfig();
            if (
                window.RuntimeController &&
                typeof window.RuntimeController.onTabActivated === "function"
            ) {
                window.RuntimeController.onTabActivated(state.tab);
            }
            if (
                window.MemesController &&
                typeof window.MemesController.onTabActivated === "function"
            ) {
                window.MemesController.onTabActivated(state.tab);
            }
        } else {
            get("appContent").style.display = "none";
            state.configLoaded = false;
        }
    } else {
        state.mobileDrawerOpen = false;
    }

    if (!state.authenticated) state.mobileDrawerOpen = false;

    const mainContent = document.querySelector(".main-content");
    if (mainContent) {
        mainContent.classList.toggle("chat-layout", state.tab === "chat");
    }

    if (initialState && initialState.version)
        get("about-version-display").innerText = initialState.version;
    if (initialState && initialState.license)
        get("about-license-display").innerText = initialState.license;

    updateAuthPanels();

    if (state.view !== "app" || !state.authenticated) {
        stopSystemTimer();
        stopLogStream();
        stopLogTimer();
    }
    if (state.view === "app" && state.tab === "logs" && state.authenticated)
        fetchLogFiles();
    updateLogRefreshState();
    syncMobileChrome();
}

function switchTab(tab) {
    abortPendingRequests(); // Cancel pending requests from previous tab
    state.tab = tab;
    state.mobileDrawerOpen = false;
    const mainContent = document.querySelector(".main-content");
    if (mainContent) {
        mainContent.classList.toggle("chat-layout", tab === "chat");
    }
    document.querySelectorAll(".nav-item").forEach((el) => {
        el.classList.toggle("active", el.getAttribute("data-tab") === tab);
    });
    document.querySelectorAll(".tab-content").forEach((el) => {
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
            if (!state.logsPaused) fetchLogs(true);
        }
    } else {
        stopLogStream();
        stopLogTimer();
    }

    if (
        window.RuntimeController &&
        typeof window.RuntimeController.onTabActivated === "function"
    ) {
        window.RuntimeController.onTabActivated(tab);
    }
    if (
        window.MemesController &&
        typeof window.MemesController.onTabActivated === "function"
    ) {
        window.MemesController.onTabActivated(tab);
    }
    syncMobileChrome();
}

function canReturnToLauncher(url) {
    try {
        const parsed = new URL(String(url || ""));
        const protocol = parsed.protocol.toLowerCase();
        const hostname = parsed.hostname.toLowerCase();
        if (protocol === "tauri:") {
            return hostname === "localhost" || hostname === "";
        }
        if (!["http:", "https:"].includes(protocol)) return false;
        return (
            hostname === "localhost" ||
            hostname === "127.0.0.1" ||
            hostname === "::1" ||
            hostname.endsWith(".localhost")
        );
    } catch (_error) {
        return false;
    }
}

function syncMobileInlinePanel(panelId, toggleId, open) {
    const panel = get(panelId);
    const toggle = get(toggleId);
    if (panel) {
        panel.classList.toggle("is-open", !!open);
    }
    if (toggle) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
}

function syncMobileChrome() {
    const drawer = get("mobileDrawer");
    const backdrop = get("mobileDrawerBackdrop");
    const menuBtn = get("mobileMenuBtn");
    const allowDrawer = state.view === "app" && state.authenticated;
    const open = allowDrawer && !!state.mobileDrawerOpen;

    if (drawer) {
        drawer.classList.toggle("is-open", open);
        drawer.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (backdrop) {
        backdrop.hidden = !open;
        backdrop.classList.toggle("is-active", open);
    }
    if (menuBtn) {
        menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    document.body.classList.toggle("is-mobile-drawer-open", open);

    syncMobileInlinePanel(
        "configSecondaryActions",
        "configMobileActionsToggle",
        !!state.configMobileActionsOpen,
    );
    syncMobileInlinePanel(
        "logsSecondaryActions",
        "logsMobileActionsToggle",
        !!state.logsMobileActionsOpen,
    );
}

function setMobileDrawerOpen(open) {
    state.mobileDrawerOpen = !!open;
    syncMobileChrome();
}

function setMobileInlineActionsOpen(key, open) {
    state[key] = !!open;
    syncMobileChrome();
}

async function init() {
    // Global error handlers
    window.onerror = function (message, source, lineno, colno, error) {
        console.error("[GlobalError]", {
            message,
            source,
            lineno,
            colno,
            error,
        });
        if (typeof showToast === "function") {
            showToast(`⚠️ ${message}`, "error", 5000);
        }
        return false;
    };

    window.onunhandledrejection = function (event) {
        const reason = event.reason;
        const msg = reason instanceof Error ? reason.message : String(reason);
        // Don't toast for routine auth errors or aborted requests
        if (
            msg === "Unauthorized" ||
            msg === "The user aborted a request." ||
            reason?.name === "AbortError"
        )
            return;
        console.error("[UnhandledRejection]", reason);
        if (typeof showToast === "function") {
            showToast(`⚠️ ${msg}`, "error", 5000);
        }
    };

    if (
        window.RuntimeController &&
        typeof window.RuntimeController.init === "function"
    ) {
        window.RuntimeController.init();
    }
    if (
        window.MemesController &&
        typeof window.MemesController.init === "function"
    ) {
        window.MemesController.init();
    }

    document.querySelectorAll('[data-action="toggle-lang"]').forEach((btn) => {
        btn.addEventListener("click", () => {
            state.lang = state.lang === "zh" ? "en" : "zh";
            setCookie("undefined_lang", state.lang);
            updateI18N();
        });
    });

    document.querySelectorAll('[data-action="toggle-theme"]').forEach((btn) => {
        btn.addEventListener("click", () =>
            applyTheme(state.theme === "dark" ? "light" : "dark"),
        );
    });

    const mobileMenuBtn = get("mobileMenuBtn");
    if (mobileMenuBtn) {
        mobileMenuBtn.onclick = () =>
            setMobileDrawerOpen(!state.mobileDrawerOpen);
    }

    const mobileDrawerCloseBtn = get("mobileDrawerCloseBtn");
    if (mobileDrawerCloseBtn) {
        mobileDrawerCloseBtn.onclick = () => setMobileDrawerOpen(false);
    }

    const mobileDrawerBackdrop = get("mobileDrawerBackdrop");
    if (mobileDrawerBackdrop) {
        mobileDrawerBackdrop.onclick = () => setMobileDrawerOpen(false);
    }

    document.querySelectorAll('[data-action="open-app"]').forEach((el) => {
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
        login(
            get("landingPasswordInput").value,
            "landingLoginStatus",
            "landingLoginBtn",
        );
    get("appLoginBtn").onclick = () =>
        login(get("appPasswordInput").value, "appLoginStatus", "appLoginBtn");

    const landingResetBtn = get("landingResetPasswordBtn");
    if (landingResetBtn) {
        landingResetBtn.onclick = () =>
            changePassword(
                "landingCurrentPasswordInput",
                "landingNewPasswordInput",
                "landingResetStatus",
                "landingResetPasswordBtn",
            );
    }
    const appResetBtn = get("appResetPasswordBtn");
    if (appResetBtn) {
        appResetBtn.onclick = () =>
            changePassword(
                "appCurrentPasswordInput",
                "appNewPasswordInput",
                "appResetStatus",
                "appResetPasswordBtn",
            );
    }

    const bindEnterLogin = (inputId, statusId, btnId) => {
        const el = get(inputId);
        if (el)
            el.addEventListener("keydown", (e) => {
                if (e.key === "Enter") login(el.value, statusId, btnId);
            });
    };
    bindEnterLogin(
        "landingPasswordInput",
        "landingLoginStatus",
        "landingLoginBtn",
    );
    bindEnterLogin("appPasswordInput", "appLoginStatus", "appLoginBtn");

    const bindEnterReset = (currentId, newId, statusId, btnId) => {
        [get(currentId), get(newId)].forEach((el) => {
            if (el)
                el.addEventListener("keydown", (e) => {
                    if (e.key === "Enter")
                        changePassword(currentId, newId, statusId, btnId);
                });
        });
    };
    bindEnterReset(
        "landingCurrentPasswordInput",
        "landingNewPasswordInput",
        "landingResetStatus",
        "landingResetPasswordBtn",
    );
    bindEnterReset(
        "appCurrentPasswordInput",
        "appNewPasswordInput",
        "appResetStatus",
        "appResetPasswordBtn",
    );

    document.querySelectorAll(".nav-item").forEach((el) => {
        el.addEventListener("click", () => {
            const v = el.getAttribute("data-view");
            const tab = el.getAttribute("data-tab");
            if (v === "landing") {
                state.view = "landing";
                refreshUI();
            } else if (tab) switchTab(tab);
            if (el.closest("#mobileDrawer")) {
                setMobileDrawerOpen(false);
            }
        });
        el.addEventListener("keydown", (e) => {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                el.click();
            }
        });
    });

    const resetBtn = get("btnResetConfig");
    if (resetBtn) resetBtn.onclick = resetConfig;

    const syncConfigBtn = get("btnSyncConfigTemplate");
    if (syncConfigBtn)
        syncConfigBtn.onclick = () => syncConfigTemplate(syncConfigBtn);

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

    const updateRestartBtn = get("btnUpdateRestart");
    if (updateRestartBtn)
        updateRestartBtn.onclick = () =>
            updateAndRestartWebui(updateRestartBtn);

    const pauseLogsBtn = get("btnPauseLogs");
    if (pauseLogsBtn) {
        pauseLogsBtn.onclick = () => {
            state.logsPaused = !state.logsPaused;
            pauseLogsBtn.innerText = state.logsPaused
                ? t("logs.resume")
                : t("logs.pause");
            renderLogs();
            updateLogRefreshState();
            if (!state.logsPaused) {
                state.logStreamFailed = false;
                fetchLogs(true);
            }
        };
    }

    document.querySelectorAll(".log-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
            setLogType(tab.dataset.logType || "bot");
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
                if (!state.logsPaused) fetchLogs(true);
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

    const logLevelGteToggle = get("logLevelGteToggle");
    if (logLevelGteToggle) {
        state.logLevelGte = logLevelGteToggle.checked;
        logLevelGteToggle.onchange = () => {
            state.logLevelGte = logLevelGteToggle.checked;
            renderLogs();
        };
    }

    const logTimeFrom = get("logTimeFrom");
    if (logTimeFrom) {
        logTimeFrom.addEventListener("change", () => {
            state.logTimeFrom = logTimeFrom.value;
            renderLogs();
        });
    }
    const logTimeTo = get("logTimeTo");
    if (logTimeTo) {
        logTimeTo.addEventListener("change", () => {
            state.logTimeTo = logTimeTo.value;
            renderLogs();
        });
    }

    const logSearchInput = get("logSearchInput");
    if (logSearchInput) {
        logSearchInput.addEventListener("input", () => {
            state.logSearch = logSearchInput.value || "";
            renderLogs();
        });
    }

    const logClearBtn = get("btnClearLogs");
    if (logClearBtn)
        logClearBtn.onclick = () => {
            state.logsRaw = "";
            renderLogs();
            showToast(t("logs.cleared"), "info");
        };

    const logCopyBtn = get("btnCopyLogs");
    if (logCopyBtn) logCopyBtn.onclick = copyLogsToClipboard;

    const logDownloadBtn = get("btnDownloadLogs");
    if (logDownloadBtn) logDownloadBtn.onclick = downloadLogs;

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

    const logsMobileActionsToggle = get("logsMobileActionsToggle");
    if (logsMobileActionsToggle) {
        logsMobileActionsToggle.onclick = () =>
            setMobileInlineActionsOpen(
                "logsMobileActionsOpen",
                !state.logsMobileActionsOpen,
            );
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

    const configMobileActionsToggle = get("configMobileActionsToggle");
    if (configMobileActionsToggle) {
        configMobileActionsToggle.onclick = () =>
            setMobileInlineActionsOpen(
                "configMobileActionsOpen",
                !state.configMobileActionsOpen,
            );
    }

    const expandAllBtn = get("btnExpandAll");
    if (expandAllBtn)
        expandAllBtn.onclick = () => setAllSectionsCollapsed(false);

    const collapseAllBtn = get("btnCollapseAll");
    if (collapseAllBtn)
        collapseAllBtn.onclick = () => setAllSectionsCollapsed(true);

    get("btnToggleToml").onclick = async function () {
        const formGrid = get("formSections");
        const tomlViewer = get("tomlViewer");
        const btn = get("btnToggleToml");
        if (!formGrid || !tomlViewer || !btn) return;

        const isShowingToml = tomlViewer.style.display !== "none";
        if (isShowingToml) {
            tomlViewer.style.display = "none";
            formGrid.style.display = "";
            btn.innerText = t("config.view_toml");
        } else {
            try {
                const res = await api("/api/config");
                const data = await res.json();
                const content = data.content || "";
                get("tomlContent").textContent = content;
                formGrid.style.display = "none";
                tomlViewer.style.display = "block";
                btn.innerText = t("config.view_form");
            } catch (e) {
                showToast(`${t("common.error")}: ${e.message}`, "error", 5000);
            }
        }
    };

    const logout = async () => {
        try {
            await api(authEndpointCandidates("logout"), { method: "POST" });
        } catch (e) {}
        state.mobileDrawerOpen = false;
        clearStoredAuthTokens();
        state.authenticated = false;
        state.view = "landing";
        if (state.launcherMode && canReturnToLauncher(state.returnTo)) {
            window.location.assign(state.returnTo);
            return;
        }
        const target = new URL(window.location.origin + "/");
        target.searchParams.set("lang", state.lang);
        target.searchParams.set("theme", state.theme);
        target.searchParams.set("view", "landing");
        window.location.assign(target.toString());
    };
    get("logoutBtn").onclick = logout;
    get("mobileLogoutBtn").onclick = logout;

    document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;
        if (state.mobileDrawerOpen) {
            setMobileDrawerOpen(false);
            return;
        }
        if (state.configMobileActionsOpen) {
            setMobileInlineActionsOpen("configMobileActionsOpen", false);
            return;
        }
        if (state.logsMobileActionsOpen) {
            setMobileInlineActionsOpen("logsMobileActionsOpen", false);
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 768) {
            state.mobileDrawerOpen = false;
            state.configMobileActionsOpen = false;
            state.logsMobileActionsOpen = false;
            syncMobileChrome();
        }
    });

    applyTheme(
        initialState && initialState.theme ? initialState.theme : "light",
    );

    try {
        const session = await checkSession();
        state.authenticated = !!session.authenticated;
        if (
            state.authenticated &&
            state.authRefreshToken &&
            state.authAccessTokenExpiresAt
        ) {
            scheduleAuthRefresh();
        }
    } catch (e) {
        state.authenticated = false;
    }

    if (state.view === "app") {
        switchTab(state.tab || "overview");
    }

    const shouldRedirectToConfig = !!(
        initialState && initialState.redirect_to_config
    );
    if (shouldRedirectToConfig) {
        state.view = "app";
        switchTab("config");
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
            if (!state.logsPaused) fetchLogs(true);
        }
    });

    refreshUI();
    if (shouldRedirectToConfig)
        showToast(t("config.bootstrap_created"), "info", 6500);
    bindLogScroll();
    fetchStatus();
    if (!document.hidden) startStatusTimer();
}

document.addEventListener("DOMContentLoaded", init);
