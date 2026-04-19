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
            showToast(
                `${t("update.not_eligible")}: ${data.reason || ""}`.trim(),
                "warning",
                7000,
            );
            return;
        }
        if (data.will_restart === false) {
            if (data.output) console.log(data.output);
            showToast(t("update.no_restart"), "warning", 8000);
            return;
        }
        showToast(
            data.updated
                ? t("update.updated_restarting")
                : t("update.uptodate_restarting"),
            data.updated ? "success" : "info",
            6000,
        );
        startWebuiRestartPoll();
    } catch (e) {
        showToast(
            `${t("update.failed")}: ${e.message || e}`.trim(),
            "error",
            8000,
        );
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
