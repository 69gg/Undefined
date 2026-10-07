const LOG_TAIL_LINES = 5000;
let _logViewGeneration = 0;
let _logFetchRequest = 0;
const _logFilesRequests = new Map();
const _logCurrentFiles = new Map();

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
    const type = state.logType;
    const file = state.logFile;
    const generation = _logViewGeneration;
    const request = ++_logFetchRequest;
    const isCurrent = () =>
        request === _logFetchRequest &&
        generation === _logViewGeneration &&
        type === state.logType &&
        file === state.logFile;
    try {
        const params = new URLSearchParams({
            lines: String(LOG_TAIL_LINES),
            type,
        });
        if (file) params.set("file", file);
        const res = await api(`/api/logs?${params.toString()}`);
        const text = await res.text();
        if (!isCurrent()) return;
        state.logsRaw = text || "";
        recordFetchSuccess("logs");
        renderLogs();
    } catch (e) {
        if (!isCurrent()) return;
        recordFetchError("logs");
        if (!container) return;
        container.dataset.placeholder = "true";
        container.innerText =
            e.message === "Unauthorized"
                ? t("logs.unauthorized")
                : t("logs.error");
        updateLogMeta(0, 0);
    }
}

function filterLogLines(raw) {
    const query = state.logSearch.trim().toLowerCase();
    const rawLines = raw ? raw.split(/\r?\n/) : [];
    const timeFrom = state.logTimeFrom
        ? new Date(state.logTimeFrom).getTime()
        : 0;
    const timeTo = state.logTimeTo ? new Date(state.logTimeTo).getTime() : 0;
    if (window.LogsController) {
        return window.LogsController.filterLogLines(raw, {
            level: state.logLevel,
            gte: state.logLevelGte,
            query,
            timeFrom: Number.isFinite(timeFrom) ? timeFrom : 0,
            timeTo: Number.isFinite(timeTo) ? timeTo : 0,
        });
    }

    const filtered = query
        ? rawLines.filter((line) => line.toLowerCase().includes(query))
        : rawLines;
    const total = rawLines.filter((line) => line.length > 0).length;
    const matched = filtered.filter((line) => line.length > 0).length;
    return { filtered, total, matched };
}

function formatLogText(text) {
    if (!text) return "";
    let escaped = escapeHtml(text);
    const query = state.logSearch.trim();
    if (query) {
        const regex = new RegExp(escapeRegExp(query), "gi");
        escaped = escaped.replace(
            regex,
            '<mark class="log-highlight">$&</mark>',
        );
    }
    escaped = escaped.replace(
        /(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)/g,
        '<span class="log-timestamp">$1</span>',
    );
    return escaped
        .replace(/\x1b\[31m/g, '<span class="ansi-red">')
        .replace(/\x1b\[32m/g, '<span class="ansi-green">')
        .replace(/\x1b\[33m/g, '<span class="ansi-yellow">')
        .replace(/\x1b\[34m/g, '<span class="ansi-blue">')
        .replace(/\x1b\[35m/g, '<span class="ansi-magenta">')
        .replace(/\x1b\[36m/g, '<span class="ansi-cyan">')
        .replace(/\x1b\[0m/g, "</span>");
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
    if (state.logAutoRefresh && state.logAtBottom)
        container.scrollTop = container.scrollHeight;
    updateLogJumpButton();
    updateLogMeta(total, matched);
}

function updateLogMeta(total, matched) {
    const meta = get("logMeta");
    if (!meta) return;
    const parts = [];
    if (state.logsPaused) parts.push(t("logs.paused"));
    if (
        state.logLevel !== "all" ||
        state.logSearch.trim() ||
        state.logLevelGte ||
        state.logTimeFrom ||
        state.logTimeTo
    ) {
        parts.push(
            `${t("logs.filtered")}: ${total > 0 ? `${matched}/${total}` : "0/0"}`,
        );
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
        state.logAtBottom =
            container.scrollHeight -
                container.scrollTop -
                container.clientHeight <
            24;
        updateLogJumpButton();
    });
    state.logScrollBound = true;
    updateLogJumpButton();
}

function startLogStream() {
    if (state.logStream || state.logStreamFailed || !window.EventSource)
        return false;
    if (!state.logStreamEnabled) return false;
    state.logStreamFailed = false;
    const params = new URLSearchParams({
        lines: String(LOG_TAIL_LINES),
        type: state.logType,
    });
    const stream = new EventSource(`/api/logs/stream?${params.toString()}`);
    state.logStream = stream;
    stream.onmessage = (event) => {
        if (state.logStream !== stream) return;
        state.logsRaw = event.data || "";
        recordFetchSuccess("logs");
        renderLogs();
    };
    stream.onerror = () => {
        if (state.logStream !== stream) return;
        state.logStreamFailed = true;
        stopLogStream();
        if (state.logAutoRefresh && !state.logsPaused) startLogTimer();
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
    if (
        state.view !== "app" ||
        state.tab !== "logs" ||
        document.hidden ||
        !state.authenticated
    ) {
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
            textarea.style.cssText = "position:fixed;opacity:0";
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
    const type = state.logType;
    const generation = _logViewGeneration;
    if (state.logFiles[type] && !force) {
        state.logFileCurrent = _logCurrentFiles.get(type) || "";
        updateLogFileSelect();
        return;
    }
    const request = (_logFilesRequests.get(type) || 0) + 1;
    _logFilesRequests.set(type, request);
    try {
        const res = await api(`/api/logs/files?type=${type}`);
        const data = await res.json();
        if (_logFilesRequests.get(type) !== request) return;
        state.logFiles[type] = data.files || [];
        _logCurrentFiles.set(type, data.current || "");
        if (state.logType !== type || generation !== _logViewGeneration) return;
        state.logFileCurrent = data.current || "";
        updateLogFileSelect();
        updateLogRefreshState();
    } catch (_error) {
        if (_logFilesRequests.get(type) !== request) return;
        state.logFiles[type] = [];
    }
}

function setLogType(type) {
    if (state.logType === type) return;
    stopLogStream();
    stopLogTimer();
    _logViewGeneration += 1;
    state.logType = type;
    state.logFile = "";
    state.logFileCurrent = "";
    state.logStreamEnabled = type !== "all";
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
