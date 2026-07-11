// Metrics history for time series chart
const METRICS_HISTORY_SIZE = 120;
const _metricsHistory = { cpu: [], memory: [], timestamps: [] };

function pushMetrics(cpuPercent, memPercent) {
    const now = new Date();
    _metricsHistory.cpu.push(cpuPercent);
    _metricsHistory.memory.push(memPercent);
    _metricsHistory.timestamps.push(now);
    if (_metricsHistory.cpu.length > METRICS_HISTORY_SIZE) {
        _metricsHistory.cpu.shift();
        _metricsHistory.memory.shift();
        _metricsHistory.timestamps.shift();
    }
}

function drawMetricsChart() {
    const canvas = get("metricsChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const pad = { top: 10, right: 12, bottom: 24, left: 36 };
    const plotW = w - pad.left - pad.right;
    const plotH = h - pad.top - pad.bottom;

    ctx.clearRect(0, 0, w, h);

    const len = _metricsHistory.cpu.length;
    if (len < 2) {
        ctx.fillStyle =
            getComputedStyle(document.documentElement)
                .getPropertyValue("--text-tertiary")
                .trim() || "#999";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Collecting data...", w / 2, h / 2);
        return;
    }

    const textColor =
        getComputedStyle(document.documentElement)
            .getPropertyValue("--text-tertiary")
            .trim() || "#999";
    const gridColor =
        getComputedStyle(document.documentElement)
            .getPropertyValue("--border-color")
            .trim() || "#333";
    const cpuColor =
        getComputedStyle(document.documentElement)
            .getPropertyValue("--accent-color")
            .trim() || "#d97757";
    const memColor =
        getComputedStyle(document.documentElement)
            .getPropertyValue("--success")
            .trim() || "#4a7c59";

    // Y axis gridlines
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 0.5;
    ctx.fillStyle = textColor;
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    for (let pct = 0; pct <= 100; pct += 25) {
        const y = pad.top + plotH - (pct / 100) * plotH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + plotW, y);
        ctx.stroke();
        ctx.fillText(`${pct}%`, pad.left - 4, y + 3);
    }

    // X axis time labels
    ctx.textAlign = "center";
    const timestamps = _metricsHistory.timestamps;
    const labelCount = Math.min(4, len);
    for (let i = 0; i < labelCount; i++) {
        const idx = Math.round((i / (labelCount - 1)) * (len - 1));
        const x = pad.left + (idx / (len - 1)) * plotW;
        const t = timestamps[idx];
        const label = `${String(t.getMinutes()).padStart(2, "0")}:${String(t.getSeconds()).padStart(2, "0")}`;
        ctx.fillText(label, x, h - 4);
    }

    function drawLine(data, color) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.beginPath();
        for (let i = 0; i < data.length; i++) {
            const x = pad.left + (i / (len - 1)) * plotW;
            const y =
                pad.top +
                plotH -
                (Math.min(100, Math.max(0, data[i])) / 100) * plotH;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();

        ctx.globalAlpha = 0.08;
        ctx.fillStyle = color;
        ctx.lineTo(pad.left + plotW, pad.top + plotH);
        ctx.lineTo(pad.left, pad.top + plotH);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
    }

    drawLine(_metricsHistory.cpu, cpuColor);
    drawLine(_metricsHistory.memory, memColor);
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
        const pidText =
            state.bot.pid != null ? `PID: ${state.bot.pid}` : "PID: --";
        const uptimeText =
            state.bot.uptime_seconds != null
                ? `Uptime: ${Math.round(state.bot.uptime_seconds)}s`
                : "";
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
    } catch (e) {}
}

function startWebuiRestartPoll() {
    let attempts = 0;
    const timer = setInterval(async () => {
        attempts += 1;
        try {
            const res = await fetch("/api/session", {
                credentials: "same-origin",
            });
            if (res.ok) {
                clearInterval(timer);
                location.reload();
            }
        } catch (e) {}
        if (attempts > 60) {
            clearInterval(timer);
            state.updateApplying = false;
            setButtonLoading(get("updateDialogConfirm"), false);
            showToast(t("update.restart_timeout"), "error", 8000);
        }
    }, 1000);
}

const UPDATE_REASON_KEYS = new Set([
    "not_a_git_repo",
    "git_not_found",
    "git_check_failed",
    "missing_origin",
    "detached_head",
    "origin_mismatch",
    "branch_mismatch",
    "dirty_worktree",
    "invalid_release_tag",
    "cannot_read_head",
    "fetch_timeout",
    "fetch_main_failed",
    "fetch_tag_failed",
    "cannot_read_remote_ref",
    "cannot_read_release_ref",
    "release_not_on_main",
    "release_not_fast_forward",
    "merge_failed",
    "updated_but_cannot_read_new_head",
]);

const UPDATE_ERROR_KEYS = new Set([
    "release_check_failed",
    "invalid_json",
    "invalid_release_tag",
    "bot_stop_timeout",
    "bot_stop_failed",
    "restore_marker_failed",
    "update_failed",
]);

function updateReasonText(reason) {
    const normalized = String(reason || "").trim();
    if (UPDATE_REASON_KEYS.has(normalized)) {
        return t(`update.reason.${normalized}`);
    }
    return normalized || t("update.reason.unknown");
}

function updateErrorText(error) {
    const normalized = String(error || "").trim();
    if (UPDATE_ERROR_KEYS.has(normalized)) {
        return t(`update.error.${normalized}`);
    }
    return normalized || t("update.failed");
}

function formatUpdateReleaseMeta(payload) {
    const release = payload?.release || {};
    const parts = [];
    if (release.name) parts.push(String(release.name));
    if (release.published_at) {
        const published = new Date(release.published_at);
        if (!Number.isNaN(published.getTime())) {
            parts.push(
                `${t("update.published")}: ${new Intl.DateTimeFormat(
                    state.lang === "zh" ? "zh-CN" : "en-US",
                    { dateStyle: "medium" },
                ).format(published)}`,
            );
        }
    }
    return parts.join(" · ");
}

function renderUpdateDialog(payload) {
    state.updateDialogPayload = payload;
    get("updateCurrentVersion").textContent = payload.current_version || "--";
    get("updateLatestVersion").textContent = payload.latest_version || "--";
    get("updateReleaseMeta").textContent = formatUpdateReleaseMeta(payload);

    const releaseLink = get("updateReleaseLink");
    const releaseUrl = String(payload?.release?.url || "").trim();
    if (releaseUrl.startsWith("https://")) {
        releaseLink.href = releaseUrl;
        releaseLink.hidden = false;
    } else {
        releaseLink.removeAttribute("href");
        releaseLink.hidden = true;
    }

    const eligibilityMessage = get("updateEligibilityMessage");
    const eligible = payload.eligible !== false;
    eligibilityMessage.hidden = eligible;
    eligibilityMessage.textContent = eligible
        ? ""
        : `${t("update.unavailable")}: ${updateReasonText(payload.reason)}`;
    const confirmButton = get("updateDialogConfirm");
    confirmButton.disabled = !eligible;
    confirmButton.setAttribute("aria-disabled", eligible ? "false" : "true");
}

function openUpdateDialog(payload) {
    const backdrop = get("updateDialogBackdrop");
    const dialog = get("updateDialog");
    if (!backdrop || !dialog) return;

    renderUpdateDialog(payload);
    state.updateDialogPreviousFocus = document.activeElement;
    backdrop.hidden = false;
    backdrop.setAttribute("aria-hidden", "false");
    document.body.classList.add("update-dialog-open");
    trapFocus(dialog);
    get("updateDialogCancel")?.focus();
}

function closeUpdateDialog() {
    if (state.updateApplying) return;
    const backdrop = get("updateDialogBackdrop");
    const dialog = get("updateDialog");
    if (!backdrop || backdrop.hidden) return;

    releaseFocus(dialog);
    backdrop.hidden = true;
    backdrop.setAttribute("aria-hidden", "true");
    document.body.classList.remove("update-dialog-open");
    state.updateDialogPayload = null;
    const previousFocus = state.updateDialogPreviousFocus;
    state.updateDialogPreviousFocus = null;
    if (previousFocus && typeof previousFocus.focus === "function") {
        previousFocus.focus();
    }
}

async function checkForUpdates({ manual = false, button = null } = {}) {
    if (!state.authenticated) {
        if (manual) showToast(t("auth.unauthorized"), "error", 5000);
        return;
    }
    if (!manual) {
        if (state.updateCheckStarted) return;
        state.updateCheckStarted = true;
    }

    if (manual) setButtonLoading(button, true);
    try {
        const endpoint = manual
            ? "/api/update-check?manual=true"
            : "/api/update-check";
        const res = await api(endpoint);
        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(updateErrorText(data.error));
        }
        if (!data.checked) return;
        if (data.update_available) {
            openUpdateDialog(data);
            return;
        }
        if (manual) showToast(t("update.up_to_date"), "success", 4000);
    } catch (error) {
        if (manual) {
            showToast(
                `${t("update.check_failed")}: ${error.message || error}`,
                "error",
                7000,
            );
        } else {
            console.debug("[UpdateCheck]", error);
        }
    } finally {
        if (manual) setButtonLoading(button, false);
    }
}

function initUpdateDialog() {
    const backdrop = get("updateDialogBackdrop");
    if (!backdrop || backdrop.dataset.bound === "true") return;
    backdrop.dataset.bound = "true";

    get("updateDialogCancel").addEventListener("click", closeUpdateDialog);
    get("updateDialogConfirm").addEventListener("click", () => {
        const payload = state.updateDialogPayload;
        if (!payload || payload.eligible === false) return;
        updateAndRestartWebui(
            get("updateDialogConfirm"),
            payload.latest_version,
        );
    });
    backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeUpdateDialog();
    });
    backdrop.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            closeUpdateDialog();
        }
    });
}

async function updateAndRestartWebui(button, targetVersion) {
    if (!state.authenticated || state.updateApplying) return;

    state.updateApplying = true;
    setButtonLoading(button, true);
    let restartScheduled = false;
    try {
        const res = await api("/api/update-restart", {
            method: "POST",
            body: JSON.stringify({ target_version: targetVersion }),
        });
        const data = await res.json();
        if (res.status === 409 && data.error === "release_changed") {
            state.updateApplying = false;
            setButtonLoading(button, false);
            closeUpdateDialog();
            showToast(t("update.release_changed"), "info", 5000);
            await checkForUpdates({ manual: true });
            return;
        }
        if (!res.ok || !data.success) {
            throw new Error(updateErrorText(data.error));
        }
        if (!data.eligible) {
            renderUpdateDialog({
                ...state.updateDialogPayload,
                eligible: false,
                reason: data.reason,
            });
            return;
        }
        if (data.will_restart === false) {
            if (data.output) console.log(data.output);
            const message =
                data.reason === "up_to_date"
                    ? t("update.up_to_date")
                    : data.uv_sync_attempted && !data.uv_synced
                      ? t("update.dependency_sync_failed")
                      : `${t("update.no_restart")}: ${updateReasonText(data.reason)}`;
            showToast(
                message,
                data.reason === "up_to_date" ? "info" : "warning",
                8000,
            );
            return;
        }
        showToast(
            data.updated
                ? t("update.updated_restarting")
                : t("update.uptodate_restarting"),
            data.updated ? "success" : "info",
            6000,
        );
        restartScheduled = true;
        startWebuiRestartPoll();
    } catch (error) {
        showToast(
            `${t("update.failed")}: ${error.message || error}`.trim(),
            "error",
            8000,
        );
    } finally {
        if (!restartScheduled) {
            state.updateApplying = false;
            setButtonLoading(button, false);
            const payload = state.updateDialogPayload;
            if (payload?.eligible === false) button.disabled = true;
        }
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
        get("systemCpuUsage").innerText =
            data.cpu_usage_percent != null ? `${cpuUsage}%` : "--";
        get("systemMemory").innerText =
            data.memory_total_gb != null && data.memory_used_gb != null
                ? `${data.memory_used_gb} GB / ${data.memory_total_gb} GB`
                : "--";
        get("systemMemoryUsage").innerText =
            data.memory_usage_percent != null ? `${memUsage}%` : "--";
        get("systemVersion").innerText = data.system_version || "--";
        get("systemArch").innerText = data.system_arch || "--";
        get("systemKernel").innerText = data.system_release || "--";
        get("systemPythonVersion").innerText = data.python_version || "--";
        get("systemUndefinedVersion").innerText =
            data.undefined_version || "--";

        get("systemCpuBar").style.width =
            `${Math.min(100, Math.max(0, cpuUsage))}%`;
        get("systemMemoryBar").style.width =
            `${Math.min(100, Math.max(0, memUsage))}%`;
        recordFetchSuccess("system");
        pushMetrics(cpuUsage, memUsage);
        drawMetricsChart();
    } catch (e) {
        recordFetchError("system");
    }
}
