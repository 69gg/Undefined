(function () {
    const runtimeState = {
        initialized: false,
        probesLoaded: false,
        memoryLoaded: false,
        runtimeMetaLoaded: false,
        runtimeEnabled: true,
        chatBusy: false,
        chatHistoryLoaded: false,
        queryBusy: {
            memory: false,
            events: false,
            profiles: false,
            profileGet: false,
        },
    };
    const RUNTIME_DISABLED_ERROR = "Runtime API disabled";

    function i18nFormat(key, params = {}) {
        let text = t(key);
        Object.keys(params).forEach((name) => {
            text = text.replaceAll(`{${name}}`, String(params[name]));
        });
        return text;
    }

    function setJsonBlock(id, payload) {
        const el = get(id);
        if (!el) return;
        el.textContent = payload ? JSON.stringify(payload, null, 2) : "--";
    }

    function appendChatMessage(role, content) {
        const log = get("runtimeChatLog");
        if (!log) return;
        const item = document.createElement("div");
        item.className = `runtime-chat-item ${role}`;
        item.innerHTML = `<div class="runtime-chat-role">${role === "user" ? "You" : "AI"}</div><div class="runtime-chat-content">${renderChatContent(content)}</div>`;
        log.appendChild(item);
        log.scrollTop = log.scrollHeight;
    }

    function clearChatMessages() {
        const log = get("runtimeChatLog");
        if (!log) return;
        log.innerHTML = "";
    }

    function parseCqAttributes(raw) {
        const attrs = {};
        String(raw || "")
            .split(",")
            .forEach((part) => {
                const idx = part.indexOf("=");
                if (idx <= 0) return;
                const key = part.slice(0, idx).trim();
                const value = part.slice(idx + 1).trim();
                if (!key) return;
                attrs[key] = value;
            });
        return attrs;
    }

    function resolveCqImageSource(attrs) {
        const raw = String((attrs && (attrs.url || attrs.file)) || "").trim();
        if (!raw) return "";
        if (raw.startsWith("base64://")) {
            const payload = raw.slice("base64://".length).trim();
            return payload ? `data:image/png;base64,${payload}` : "";
        }
        if (raw.startsWith("/") || /^[A-Za-z]:[\\/]/.test(raw)) {
            return `/api/runtime/chat/image?path=${encodeURIComponent(raw)}`;
        }
        if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("data:image/")) {
            return raw;
        }
        return "";
    }

    function renderChatContent(content) {
        const text = String(content || "");
        const imagePattern = /\[CQ:image,([^\]]+)\]/g;
        let html = "";
        let cursor = 0;
        let match = imagePattern.exec(text);
        while (match) {
            const start = match.index;
            if (start > cursor) {
                html += escapeHtml(text.slice(cursor, start));
            }
            const attrs = parseCqAttributes(match[1]);
            const src = resolveCqImageSource(attrs);
            if (src) {
                html += `<img class="runtime-chat-image" src="${escapeHtml(src)}" alt="image" loading="lazy" />`;
            } else {
                html += `<code>${escapeHtml(match[0])}</code>`;
            }
            cursor = imagePattern.lastIndex;
            match = imagePattern.exec(text);
        }
        if (cursor < text.length) {
            html += escapeHtml(text.slice(cursor));
        }
        return html || escapeHtml(text);
    }

    function readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ""));
            reader.onerror = () => reject(new Error("File read failed"));
            reader.readAsDataURL(file);
        });
    }

    async function parseJsonSafe(res) {
        try {
            return await res.json();
        } catch (_error) {
            return null;
        }
    }

    function buildRequestError(res, payload) {
        const fallback = `${res.status} ${res.statusText || "Request failed"}`.trim();
        if (!payload || typeof payload !== "object") return fallback;
        const base = payload.error ? String(payload.error) : fallback;
        return payload.detail ? `${base}: ${payload.detail}` : base;
    }

    function appendRuntimeApiHint(message) {
        const text = String(message || "").trim();
        if (!text) return text;
        const normalized = text.toLowerCase();
        const unreachable = normalized.includes("runtime api unreachable")
            || normalized.includes("failed to fetch")
            || normalized.includes("networkerror")
            || normalized.includes(" 502 ")
            || normalized.startsWith("502 ");
        if (!unreachable) return text;
        const hint = t("runtime.api_start_hint");
        if (!hint || text.includes(hint)) return text;
        return `${text} ${hint}`;
    }

    async function consumeSse(res, onEvent) {
        if (!res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        function emitBlock(rawBlock) {
            const block = String(rawBlock || "").trim();
            if (!block) return;
            let event = "message";
            const dataLines = [];
            block.split("\n").forEach((line) => {
                if (line.startsWith(":")) return;
                if (line.startsWith("event:")) {
                    event = line.slice(6).trim() || "message";
                    return;
                }
                if (line.startsWith("data:")) {
                    dataLines.push(line.slice(5).trimStart());
                }
            });
            if (dataLines.length === 0) return;
            const rawData = dataLines.join("\n");
            let payload = {};
            try {
                payload = JSON.parse(rawData);
            } catch (_error) {
                payload = { raw: rawData };
            }
            onEvent(event, payload);
        }

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            buffer = buffer.replace(/\r\n/g, "\n");
            let boundary = buffer.indexOf("\n\n");
            while (boundary !== -1) {
                const block = buffer.slice(0, boundary);
                buffer = buffer.slice(boundary + 2);
                emitBlock(block);
                boundary = buffer.indexOf("\n\n");
            }
        }
        buffer += decoder.decode();
        if (buffer.trim()) emitBlock(buffer);
    }

    function renderMemoryItems(items) {
        const container = get("runtimeMemoryList");
        const meta = get("runtimeMemoryMeta");
        if (!container || !meta) return;
        if (!Array.isArray(items) || items.length === 0) {
            meta.textContent = i18nFormat("runtime.total", { count: 0 });
            container.innerHTML = `<div class="empty-state">${t("runtime.empty")}</div>`;
            return;
        }
        meta.textContent = i18nFormat("runtime.total", { count: items.length });
        container.innerHTML = items
            .map((item) => {
                const uuid = escapeHtml(item.uuid || "");
                const fact = escapeHtml(item.fact || "");
                const created = escapeHtml(item.created_at || "");
                return `<div class="runtime-list-item"><div class="runtime-list-head"><code>${uuid}</code><span>${created}</span></div><div class="runtime-list-fact">${fact}</div></div>`;
            })
            .join("");
    }

    function setProbeUnavailable(message) {
        const msg = String(message || RUNTIME_DISABLED_ERROR);
        setJsonBlock("runtimeProbeInternal", { error: msg });
        setJsonBlock("runtimeProbeExternal", { error: msg });
    }

    function setMemoryUnavailable(message) {
        const msg = String(message || RUNTIME_DISABLED_ERROR);
        const container = get("runtimeMemoryList");
        const meta = get("runtimeMemoryMeta");
        if (meta) meta.textContent = msg;
        if (container) {
            container.innerHTML = `<div class="empty-state">${escapeHtml(msg)}</div>`;
        }
        setJsonBlock("runtimeEventsResult", { error: msg });
        setJsonBlock("runtimeProfilesResult", { error: msg });
        setJsonBlock("runtimeProfileResult", { error: msg });
    }

    async function fetchRuntimeMeta() {
        const res = await api("/api/runtime/meta");
        const data = await res.json();
        return data;
    }

    async function ensureRuntimeEnabled() {
        if (runtimeState.runtimeMetaLoaded) {
            return runtimeState.runtimeEnabled;
        }
        const meta = await fetchRuntimeMeta();
        runtimeState.runtimeMetaLoaded = true;
        runtimeState.runtimeEnabled = !!(meta && meta.enabled);
        return runtimeState.runtimeEnabled;
    }

    async function fetchInternalProbe() {
        const res = await api("/api/runtime/probes/internal");
        const data = await res.json();
        setJsonBlock("runtimeProbeInternal", data);
    }

    async function fetchExternalProbe() {
        const res = await api("/api/runtime/probes/external");
        const data = await res.json();
        setJsonBlock("runtimeProbeExternal", data);
    }

    async function searchMemory() {
        if (!(await ensureRuntimeEnabled())) {
            setMemoryUnavailable(t("runtime.disabled"));
            return;
        }
        const input = get("runtimeMemoryQuery");
        const query = (input && input.value ? input.value : "").trim();
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        const res = await api(`/api/runtime/memory?${params.toString()}`);
        const data = await res.json();
        renderMemoryItems(data.items || []);
    }

    async function searchEvents() {
        if (!(await ensureRuntimeEnabled())) {
            setJsonBlock("runtimeEventsResult", { error: t("runtime.disabled") });
            return;
        }
        const input = get("runtimeEventsQuery");
        const query = (input && input.value ? input.value : "").trim();
        if (!query) {
            setJsonBlock("runtimeEventsResult", { error: "q is required" });
            return;
        }
        const params = new URLSearchParams({ q: query });
        const res = await api(`/api/runtime/cognitive/events?${params.toString()}`);
        const data = await res.json();
        setJsonBlock("runtimeEventsResult", data);
    }

    async function searchProfiles() {
        if (!(await ensureRuntimeEnabled())) {
            setJsonBlock("runtimeProfilesResult", { error: t("runtime.disabled") });
            return;
        }
        const input = get("runtimeProfilesQuery");
        const query = (input && input.value ? input.value : "").trim();
        if (!query) {
            setJsonBlock("runtimeProfilesResult", { error: "q is required" });
            return;
        }
        const params = new URLSearchParams({ q: query });
        const res = await api(`/api/runtime/cognitive/profiles?${params.toString()}`);
        const data = await res.json();
        setJsonBlock("runtimeProfilesResult", data);
    }

    async function fetchProfileByEntity() {
        if (!(await ensureRuntimeEnabled())) {
            setJsonBlock("runtimeProfileResult", { error: t("runtime.disabled") });
            return;
        }
        const typeInput = get("runtimeProfileEntityType");
        const idInput = get("runtimeProfileEntityId");
        const entityType = (typeInput && typeInput.value ? typeInput.value : "").trim();
        const entityId = (idInput && idInput.value ? idInput.value : "").trim();
        if (!entityType || !entityId) {
            setJsonBlock("runtimeProfileResult", { error: "entity_type/entity_id are required" });
            return;
        }
        const res = await api(`/api/runtime/cognitive/profile/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`);
        const data = await res.json();
        setJsonBlock("runtimeProfileResult", data);
    }

    async function runQueryAction(kind, buttonId, action) {
        if (runtimeState.queryBusy[kind]) return;
        runtimeState.queryBusy[kind] = true;
        const button = get(buttonId);
        setButtonLoading(button, true);
        try {
            await action();
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000
            );
        } finally {
            setButtonLoading(button, false);
            runtimeState.queryBusy[kind] = false;
        }
    }

    async function loadChatHistory(force = false) {
        if (runtimeState.chatHistoryLoaded && !force) return;
        const res = await api("/api/runtime/chat/history?limit=200");
        const data = await parseJsonSafe(res);
        if (!res.ok || (data && data.error)) {
            throw new Error(buildRequestError(res, data));
        }

        clearChatMessages();
        const items = data && Array.isArray(data.items) ? data.items : [];
        items.forEach((item) => {
            const role = item && item.role === "bot" ? "bot" : "user";
            const content = String((item && item.content) || "").trim();
            if (!content) return;
            appendChatMessage(role, content);
        });
        runtimeState.chatHistoryLoaded = true;
    }

    async function sendChatMessage() {
        if (runtimeState.chatBusy) return;
        const input = get("runtimeChatInput");
        const button = get("btnRuntimeChatSend");
        if (!input) return;
        const message = (input.value || "").trim();
        if (!message) return;

        runtimeState.chatBusy = true;
        setButtonLoading(button, true);
        appendChatMessage("user", message);
        input.value = "";

        try {
            const res = await api("/api/runtime/chat", {
                method: "POST",
                headers: { Accept: "text/event-stream" },
                body: JSON.stringify({ message, stream: true }),
            });

            const contentType = (res.headers.get("Content-Type") || "").toLowerCase();
            if (contentType.includes("text/event-stream") && res.body) {
                let replied = false;
                let streamError = "";
                let donePayload = null;
                await consumeSse(res, (event, payload) => {
                    if (event === "message") {
                        const content = String(
                            payload && (payload.content ?? payload.message)
                                ? payload.content ?? payload.message
                                : ""
                        ).trim();
                        if (!content) return;
                        appendChatMessage("bot", content);
                        replied = true;
                        return;
                    }
                    if (event === "error") {
                        streamError = String(
                            payload && (payload.error || payload.message)
                                ? payload.error || payload.message
                                : "stream error"
                        );
                        return;
                    }
                    if (event === "done") {
                        donePayload = payload;
                    }
                });
                if (streamError) {
                    throw new Error(streamError);
                }
                if (!replied && donePayload && donePayload.reply) {
                    appendChatMessage("bot", String(donePayload.reply));
                    replied = true;
                }
                if (!replied) {
                    appendChatMessage("bot", t("runtime.empty"));
                }
                runtimeState.chatHistoryLoaded = true;
                return;
            }

            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }

            const messages = data && Array.isArray(data.messages) ? data.messages : [];
            if (messages.length > 0) {
                messages.forEach((msg) => appendChatMessage("bot", String(msg || "")));
            } else if (data && data.reply) {
                appendChatMessage("bot", String(data.reply));
            } else {
                appendChatMessage("bot", t("runtime.empty"));
            }
            runtimeState.chatHistoryLoaded = true;
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000
            );
        } finally {
            runtimeState.chatBusy = false;
            setButtonLoading(button, false);
        }
    }

    async function handleChatImagePicked(event) {
        const input = event && event.target ? event.target : null;
        const files = input && input.files ? Array.from(input.files) : [];
        const chatInput = get("runtimeChatInput");
        if (!chatInput || files.length === 0) return;

        try {
            for (const file of files) {
                if (!file || !String(file.type || "").startsWith("image/")) continue;
                const dataUrl = await readFileAsDataUrl(file);
                const base64 = String(dataUrl).split(",", 2)[1] || "";
                if (!base64) continue;
                if (chatInput.value && !chatInput.value.endsWith("\n")) {
                    chatInput.value += "\n";
                }
                chatInput.value += `[CQ:image,file=base64://${base64}]`;
            }
            showToast(t("runtime.image_added"), "success", 1800);
            chatInput.focus();
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000
            );
        } finally {
            if (input) input.value = "";
        }
    }

    async function refreshProbes() {
        try {
            if (!(await ensureRuntimeEnabled())) {
                setProbeUnavailable(t("runtime.disabled"));
                runtimeState.probesLoaded = true;
                return;
            }

            await Promise.all([fetchInternalProbe(), fetchExternalProbe()]);
            runtimeState.probesLoaded = true;
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000
            );
        }
    }

    async function refreshMemory() {
        try {
            if (!(await ensureRuntimeEnabled())) {
                setMemoryUnavailable(t("runtime.disabled"));
                runtimeState.memoryLoaded = true;
                return;
            }
            await searchMemory();
            runtimeState.memoryLoaded = true;
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000
            );
        }
    }

    async function refreshAll() {
        await Promise.all([refreshProbes(), refreshMemory()]);
    }

    function bindEvents() {
        const bindEnter = (id, handler) => {
            const input = get(id);
            if (!input) return;
            input.addEventListener("keydown", (event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    handler();
                }
            });
        };

        const probeRefresh = get("btnProbeRefresh");
        if (probeRefresh) probeRefresh.addEventListener("click", refreshProbes);

        const memoryRefresh = get("btnMemoryRefresh");
        if (memoryRefresh) memoryRefresh.addEventListener("click", refreshMemory);

        const runMemorySearch = () => runQueryAction("memory", "btnRuntimeMemorySearch", searchMemory);
        const runEventsSearch = () => runQueryAction("events", "btnRuntimeEventsSearch", searchEvents);
        const runProfilesSearch = () => runQueryAction("profiles", "btnRuntimeProfilesSearch", searchProfiles);
        const runProfileGet = () => runQueryAction("profileGet", "btnRuntimeProfileGet", fetchProfileByEntity);

        const memoryBtn = get("btnRuntimeMemorySearch");
        if (memoryBtn) memoryBtn.addEventListener("click", runMemorySearch);
        bindEnter("runtimeMemoryQuery", runMemorySearch);

        const eventsBtn = get("btnRuntimeEventsSearch");
        if (eventsBtn) eventsBtn.addEventListener("click", runEventsSearch);
        bindEnter("runtimeEventsQuery", runEventsSearch);

        const profilesBtn = get("btnRuntimeProfilesSearch");
        if (profilesBtn) profilesBtn.addEventListener("click", runProfilesSearch);
        bindEnter("runtimeProfilesQuery", runProfilesSearch);

        const profileGetBtn = get("btnRuntimeProfileGet");
        if (profileGetBtn) profileGetBtn.addEventListener("click", runProfileGet);
        bindEnter("runtimeProfileEntityType", runProfileGet);
        bindEnter("runtimeProfileEntityId", runProfileGet);

        const sendBtn = get("btnRuntimeChatSend");
        if (sendBtn) sendBtn.addEventListener("click", sendChatMessage);

        const imageBtn = get("btnRuntimeChatImage");
        const imageInput = get("runtimeChatImageInput");
        if (imageBtn && imageInput) {
            imageBtn.addEventListener("click", () => {
                imageInput.click();
            });
            imageInput.addEventListener("change", handleChatImagePicked);
        }

        const chatInput = get("runtimeChatInput");
        if (chatInput) {
            chatInput.addEventListener("keydown", (event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendChatMessage();
                }
            });
        }
    }

    function onTabActivated(tab) {
        if (!state.authenticated) return;
        if (tab === "probes") {
            if (!runtimeState.probesLoaded) {
                refreshProbes();
            }
            return;
        }
        if (tab === "memory") {
            if (!runtimeState.memoryLoaded) {
                refreshMemory();
            }
            return;
        }
        if (tab === "chat") {
            loadChatHistory().catch((error) => {
                showToast(
                    `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                    "error",
                    5000
                );
            });
        }
    }

    function init() {
        if (runtimeState.initialized) return;
        bindEvents();
        runtimeState.initialized = true;
    }

    window.RuntimeController = {
        init,
        onTabActivated,
        refreshProbes,
        refreshMemory,
        refreshAll,
        loadChatHistory,
    };
})();
