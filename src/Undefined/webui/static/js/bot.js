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
        const pidText = state.bot.pid != null ? `PID: ${state.bot.pid}` : "PID: --";
        const uptimeText = state.bot.uptime_seconds != null ? `Uptime: ${Math.round(state.bot.uptime_seconds)}s` : "";
        const parts = [pidText, uptimeText].filter(Boolean);
        metaL.innerText = parts.length ? parts.join(" | ") : "--";
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

function startWebuiRestartPoll() {
    let attempts = 0;
    const timer = setInterval(async () => {
        attempts += 1;
        try {
            const res = await fetch("/api/session", { credentials: "same-origin" });
            if (res.ok) { clearInterval(timer); location.reload(); }
        } catch (e) { }
        if (attempts > 60) clearInterval(timer);
    }, 1000);
}

async function updateAndRestartWebui(button) {
    if (!state.authenticated) {
        showToast(t("auth.unauthorized"), "error", 5000);
        return;
    }
    setButtonLoading(button, true);
    try {
        showToast(t("update.working"), "info", 4000);
        const res = await api("/api/update-restart", { method: "POST" });
        const data = await res.json();
        if (!data.success) throw new Error(data.error || t("update.failed"));
        if (!data.eligible) {
            showToast(`${t("update.not_eligible")}: ${data.reason || ""}`.trim(), "warning", 7000);
            return;
        }
        if (data.will_restart === false) {
            if (data.output) console.log(data.output);
            showToast(t("update.no_restart"), "warning", 8000);
            return;
        }
        showToast(data.updated ? t("update.updated_restarting") : t("update.uptodate_restarting"),
            data.updated ? "success" : "info", 6000);
        startWebuiRestartPoll();
    } catch (e) {
        showToast(`${t("update.failed")}: ${e.message || e}`.trim(), "error", 8000);
    } finally {
        setButtonLoading(button, false);
    }
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
                ? `${data.memory_used_gb} GB / ${data.memory_total_gb} GB` : "--";
        get("systemMemoryUsage").innerText = data.memory_usage_percent != null ? `${memUsage}%` : "--";
        get("systemVersion").innerText = data.system_version || "--";
        get("systemArch").innerText = data.system_arch || "--";
        get("systemKernel").innerText = data.system_release || "--";
        get("systemPythonVersion").innerText = data.python_version || "--";
        get("systemUndefinedVersion").innerText = data.undefined_version || "--";

        get("systemCpuBar").style.width = `${Math.min(100, Math.max(0, cpuUsage))}%`;
        get("systemMemoryBar").style.width = `${Math.min(100, Math.max(0, memUsage))}%`;
        recordFetchSuccess("system");
    } catch (e) {
        recordFetchError("system");
    }
}
