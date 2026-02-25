(function () {
    const runtimeState = {
        initialized: false,
        loaded: false,
        chatBusy: false,
    };

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
        item.innerHTML = `<div class="runtime-chat-role">${role === "user" ? "You" : "AI"}</div><div class="runtime-chat-content">${escapeHtml(content)}</div>`;
        log.appendChild(item);
        log.scrollTop = log.scrollHeight;
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

    async function fetchRuntimeMeta() {
        const res = await api("/api/runtime/meta");
        const data = await res.json();
        return data;
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
        const input = get("runtimeMemoryQuery");
        const query = (input && input.value ? input.value : "").trim();
        const params = new URLSearchParams();
        if (query) params.set("q", query);
        const res = await api(`/api/runtime/memory?${params.toString()}`);
        const data = await res.json();
        renderMemoryItems(data.items || []);
    }

    async function searchEvents() {
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
        } catch (error) {
            showToast(`${t("runtime.failed")}: ${error.message || error}`, "error", 5000);
        } finally {
            runtimeState.chatBusy = false;
            setButtonLoading(button, false);
        }
    }

    async function refreshAll() {
        try {
            const meta = await fetchRuntimeMeta();
            if (!meta.enabled) {
                setJsonBlock("runtimeProbeInternal", { error: "Runtime API disabled" });
                setJsonBlock("runtimeProbeExternal", { error: "Runtime API disabled" });
                renderMemoryItems([]);
                return;
            }

            await Promise.all([
                fetchInternalProbe(),
                fetchExternalProbe(),
                searchMemory(),
            ]);

            runtimeState.loaded = true;
        } catch (error) {
            showToast(`${t("runtime.failed")}: ${error.message || error}`, "error", 5000);
        }
    }

    function bindEvents() {
        const refresh = get("btnRuntimeRefresh");
        if (refresh) refresh.addEventListener("click", refreshAll);

        const memoryBtn = get("btnRuntimeMemorySearch");
        if (memoryBtn) memoryBtn.addEventListener("click", searchMemory);

        const eventsBtn = get("btnRuntimeEventsSearch");
        if (eventsBtn) eventsBtn.addEventListener("click", searchEvents);

        const profilesBtn = get("btnRuntimeProfilesSearch");
        if (profilesBtn) profilesBtn.addEventListener("click", searchProfiles);

        const profileGetBtn = get("btnRuntimeProfileGet");
        if (profileGetBtn) profileGetBtn.addEventListener("click", fetchProfileByEntity);

        const sendBtn = get("btnRuntimeChatSend");
        if (sendBtn) sendBtn.addEventListener("click", sendChatMessage);

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
        if (tab !== "runtime") return;
        if (!state.authenticated) return;
        if (!runtimeState.loaded) {
            refreshAll();
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
        refreshAll,
    };
})();
