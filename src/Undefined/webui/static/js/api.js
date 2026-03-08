const AUTH_ENDPOINTS = {
    login: [
        "/api/v1/management/auth/login",
        "/api/v1/management/login",
        "/api/login",
    ],
    refresh: [
        "/api/v1/management/auth/refresh",
        "/api/v1/management/refresh",
        "/api/refresh",
    ],
    session: [
        "/api/v1/management/auth/session",
        "/api/v1/management/session",
        "/api/session",
    ],
    logout: [
        "/api/v1/management/auth/logout",
        "/api/v1/management/logout",
        "/api/logout",
    ],
};

function authEndpointCandidates(name) {
    return Array.isArray(AUTH_ENDPOINTS[name]) ? AUTH_ENDPOINTS[name] : [];
}

function shouldRetryCandidate(res) {
    return !!res && [404, 405, 501].includes(res.status);
}

async function requestOnce(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.method === "POST" && options.body && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
    }
    if (state.authAccessToken && !headers.Authorization) {
        headers.Authorization = `Bearer ${state.authAccessToken}`;
    }
    return fetch(path, {
        ...options,
        headers,
        credentials: options.credentials || "same-origin",
    });
}

async function apiWithFallback(paths, options = {}) {
    const candidates = Array.isArray(paths) ? paths : [paths];
    let lastResponse = null;
    for (const path of candidates) {
        const response = await requestOnce(path, options);
        lastResponse = response;
        if (
            !shouldRetryCandidate(response) ||
            path === candidates[candidates.length - 1]
        ) {
            return response;
        }
    }
    return lastResponse;
}

function normalizeAuthPayload(payload) {
    const source =
        payload && payload.tokens && typeof payload.tokens === "object"
            ? payload.tokens
            : payload || {};
    const accessToken = String(
        source.access_token || source.accessToken || "",
    ).trim();
    const refreshToken = String(
        source.refresh_token || source.refreshToken || "",
    ).trim();
    const expiresIn =
        Number.parseInt(
            String(source.expires_in || source.expiresIn || "0"),
            10,
        ) || 0;
    const expiresAtRaw =
        Number.parseInt(
            String(
                source.access_token_expires_at ||
                    source.accessTokenExpiresAt ||
                    "0",
            ),
            10,
        ) || 0;
    const accessTokenExpiresAt =
        expiresAtRaw > 0
            ? expiresAtRaw
            : expiresIn > 0
              ? Date.now() + expiresIn * 1000
              : 0;
    return { accessToken, refreshToken, accessTokenExpiresAt };
}

function scheduleAuthRefresh() {
    if (state.authRefreshTimer) {
        clearTimeout(state.authRefreshTimer);
        state.authRefreshTimer = null;
    }
    if (!state.authRefreshToken || !state.authAccessTokenExpiresAt) {
        return;
    }
    const delay = Math.max(
        10_000,
        state.authAccessTokenExpiresAt - Date.now() - 60_000,
    );
    state.authRefreshTimer = window.setTimeout(() => {
        refreshAccessToken().catch(() => {
            // keep silent; next user action will force re-auth if needed
        });
    }, delay);
}

function updateAuthFromPayload(payload) {
    const next = normalizeAuthPayload(payload);
    if (!next.accessToken && !next.refreshToken) {
        return false;
    }
    storeAuthTokens(next);
    scheduleAuthRefresh();
    return true;
}

async function refreshAccessToken() {
    if (!state.authRefreshToken) {
        throw new Error("Unauthorized");
    }
    const response = await apiWithFallback(authEndpointCandidates("refresh"), {
        method: "POST",
        body: JSON.stringify({ refresh_token: state.authRefreshToken }),
        headers: state.authAccessToken
            ? { Authorization: `Bearer ${state.authAccessToken}` }
            : {},
    });
    const payload = await response
        .clone()
        .json()
        .catch(() => ({}));
    if (!response.ok || !updateAuthFromPayload(payload)) {
        clearStoredAuthTokens();
        throw new Error("Unauthorized");
    }
    return payload;
}

async function api(path, options = {}) {
    const candidates = Array.isArray(path) ? path : [path];
    const method = String(options.method || "GET").toUpperCase();
    const accessExpiringSoon =
        !!state.authRefreshToken &&
        !!state.authAccessTokenExpiresAt &&
        state.authAccessTokenExpiresAt <= Date.now() + 60_000;

    if (accessExpiringSoon && method !== "OPTIONS") {
        try {
            await refreshAccessToken();
        } catch (_error) {
            // ignore and let request surface authorization result
        }
    }

    let res = await apiWithFallback(candidates, options);
    if (
        res.status === 401 &&
        state.authRefreshToken &&
        !options._skipRefreshRetry
    ) {
        try {
            await refreshAccessToken();
            res = await apiWithFallback(candidates, {
                ...options,
                _skipRefreshRetry: true,
            });
        } catch (_error) {
            clearStoredAuthTokens();
        }
    }
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
        state.systemTimer = setInterval(
            fetchSystemInfo,
            REFRESH_INTERVALS.system,
        );
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
