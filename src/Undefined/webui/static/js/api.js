async function api(path, options = {}) {
    const headers = options.headers || {};
    if (options.method === "POST" && options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, {
        ...options,
        headers,
        credentials: options.credentials || "same-origin",
    });
    if (res.status === 401) {
        state.authenticated = false;
        refreshUI();
        throw new Error("Unauthorized");
    }
    return res;
}

function shouldFetch(kind) {
    return Date.now() >= (state.nextFetchAt[kind] || 0);
}

function recordFetchError(kind) {
    const current = state.fetchBackoff[kind] || 0;
    const next = Math.min(5, current + 1);
    state.fetchBackoff[kind] = next;
    state.nextFetchAt[kind] = Date.now() + Math.min(15000, 1000 * 2 ** next);
}

function recordFetchSuccess(kind) {
    state.fetchBackoff[kind] = 0;
    state.nextFetchAt[kind] = 0;
}

function startStatusTimer() {
    if (!state.statusTimer) {
        state.statusTimer = setInterval(fetchStatus, REFRESH_INTERVALS.status);
    }
}

function stopStatusTimer() {
    if (state.statusTimer) {
        clearInterval(state.statusTimer);
        state.statusTimer = null;
    }
}

function startSystemTimer() {
    if (!state.systemTimer) {
        state.systemTimer = setInterval(fetchSystemInfo, REFRESH_INTERVALS.system);
    }
}

function stopSystemTimer() {
    if (state.systemTimer) {
        clearInterval(state.systemTimer);
        state.systemTimer = null;
    }
}

function startLogTimer() {
    if (!state.logTimer) {
        state.logTimer = setInterval(fetchLogs, REFRESH_INTERVALS.logs);
    }
}

function stopLogTimer() {
    if (state.logTimer) {
        clearInterval(state.logTimer);
        state.logTimer = null;
    }
}
