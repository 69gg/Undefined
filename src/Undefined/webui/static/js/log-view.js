async function fetchLogs(force = false) {
    if (!force && !shouldFetch("logs")) return;
    const container = get("logContainer");
    if (container && !state.logsRaw) {
        container.dataset.placeholder = "true";
        container.innerText = t("logs.initializing");
    }
    if (state.logType === "all" && !state.logFile) {
        state.logsRaw = "";
        renderLogs();
        return;
    }
    try {
        const params = new URLSearchParams({ lines: "200", type: state.logType });
        if (state.logFile) params.set("file", state.logFile);
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

function filterLogLines(raw) {
    const query = state.logSearch.trim().toLowerCase();
    const rawLines = raw ? raw.split(/\r?\n/) : [];
    const base = window.LogsController
        ? window.LogsController.filterLogLines(raw, { level: state.logLevel, gte: state.logLevelGte })
        : { filtered: rawLines, total: rawLines.length };

    let filtered = base.filtered;
    if (query) filtered = filtered.filter(line => line.toLowerCase().includes(query));

    const total = base.total ?? rawLines.length;
    const matched = filtered.filter(line => line.length > 0).length;
    return { filtered, total, matched };
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
    container.innerHTML = formatLogText(filtered.join("\n"));
    container.dataset.placeholder = "false";
    if (state.logAutoRefresh && state.logAtBottom) container.scrollTop = container.scrollHeight;
    updateLogJumpButton();
    updateLogMeta(total, matched);
}

function updateLogMeta(total, matched) {
    const meta = get("logMeta");
    if (!meta) return;
    const parts = [];
    if (state.logsPaused) parts.push(t("logs.paused"));
    if (state.logLevel !== "all" || state.logSearch.trim() || state.logLevelGte) {
        parts.push(`${t("logs.filtered")}: ${total > 0 ? `${matched}/${total}` : "0/0"}`);
    }
    meta.innerText = parts.join(" | ");
}

function updateLogJumpButton() {
    const button = get("btnJumpLogs");
    if (!button) return;
    button.style.visibility = state.logAtBottom ? "hidden" : "visible";
    button.style.pointerEvents = state.logAtBottom ? "none" : "auto";
}

function bindLogScroll() {
    if (state.logScrollBound) return;
    const container = get("logContainer");
    if (!container) return;
    container.addEventListener("scroll", () => {
        state.logAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 24;
        updateLogJumpButton();
    });
    state.logScrollBound = true;
    updateLogJumpButton();
}

function startLogStream() {
    if (state.logStream || state.logStreamFailed || !window.EventSource) return false;
    if (!state.logStreamEnabled) return false;
    state.logStreamFailed = false;
    const params = new URLSearchParams({ lines: "200", type: state.logType });
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
        if (state.logAutoRefresh && !state.logsPaused) startLogTimer();
    };
    return true;
}

function stopLogStream() {
    if (state.logStream) { state.logStream.close(); state.logStream = null; }
}

function updateLogRefreshState() {
    if (state.view !== "app" || state.tab !== "logs" || document.hidden || !state.authenticated) {
        stopLogStream(); stopLogTimer(); return;
    }
    if (state.logsPaused || !state.logAutoRefresh) {
        stopLogStream(); stopLogTimer(); return;
    }
    if (!state.logStreamEnabled) { stopLogStream(); startLogTimer(); return; }
    if (startLogStream()) { stopLogTimer(); return; }
    startLogTimer();
}

async function copyLogsToClipboard() {
    const text = state.logsRaw || "";
    if (!text) { showToast(t("logs.empty"), "info"); return; }
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
        } else {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.style.cssText = "position:fixed;opacity:0";
            document.body.appendChild(textarea);
            textarea.focus(); textarea.select();
            document.execCommand("copy");
            textarea.remove();
        }
        showToast(t("logs.copied"), "success");
    } catch (e) {
        showToast(`${t("common.error")}: ${e.message}`, "error");
    }
}

async function fetchLogFiles(force = false) {
    if (state.logFiles[state.logType] && !force) { updateLogFileSelect(); return; }
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
    if (!text) { showToast(t("logs.empty"), "info"); return; }
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
