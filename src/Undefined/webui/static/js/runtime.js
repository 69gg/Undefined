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

    function readInputValue(id) {
        const el = get(id);
        if (!el) return "";
        return String(el.value || "").trim();
    }

    function appendQueryParam(params, key, value) {
        const text = String(value || "").trim();
        if (!text) return;
        params.set(key, text);
    }

    function appendPositiveIntParam(params, key, value) {
        const text = String(value || "").trim();
        if (!text) return;
        const num = Number.parseInt(text, 10);
        if (!Number.isFinite(num) || num <= 0) return;
        params.set(key, String(num));
    }

    function formatNumeric(value, digits = 4) {
        const num = Number(value);
        if (!Number.isFinite(num)) return "";
        return num.toFixed(digits);
    }

    function renderStructuredText(text) {
        const raw = String(text || "").trim();
        if (!raw) return escapeHtml(text || "");

        if ((raw.startsWith("{") && raw.endsWith("}")) || (raw.startsWith("[") && raw.endsWith("]"))) {
            try {
                const parsed = JSON.parse(raw);
                return `<pre class="runtime-json runtime-json-inline">${escapeHtml(JSON.stringify(parsed, null, 2))}</pre>`;
            } catch (_error) {
                // Fall through to line-based rendering.
            }
        }

        const lines = raw.split(/\r?\n/);
        const blocks = [];
        let listItems = [];

        const flushList = () => {
            if (!listItems.length) return;
            blocks.push(`<ul class="runtime-profile-list">${listItems.join("")}</ul>`);
            listItems = [];
        };

        for (const line of lines) {
            const textLine = String(line || "").trim();
            if (!textLine) {
                flushList();
                continue;
            }

            const heading = textLine.match(/^#{1,3}\s+(.+)$/);
            if (heading) {
                flushList();
                blocks.push(`<div class="runtime-profile-title">${escapeHtml(heading[1])}</div>`);
                continue;
            }

            const bullet = textLine.match(/^[-*]\s+(.+)$/);
            if (bullet) {
                listItems.push(`<li>${escapeHtml(bullet[1])}</li>`);
                continue;
            }

            const kv = textLine.match(/^([^:：]{1,32})[:：]\s*(.+)$/);
            if (kv) {
                flushList();
                blocks.push(
                    `<div class="runtime-profile-kv"><span class="runtime-profile-k">${escapeHtml(kv[1])}</span><span class="runtime-profile-v">${escapeHtml(kv[2])}</span></div>`
                );
                continue;
            }

            flushList();
            blocks.push(`<p class="runtime-profile-p">${escapeHtml(textLine)}</p>`);
        }
        flushList();
        return blocks.join("") || `<p class="runtime-profile-p">${escapeHtml(raw)}</p>`;
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

    async function fetchJsonOrThrow(path) {
        const res = await api(path);
        const data = await parseJsonSafe(res);
        if (!res.ok || (data && data.error)) {
            throw new Error(buildRequestError(res, data));
        }
        return data || {};
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

    function renderMemoryItems(payload) {
        const container = get("runtimeMemoryList");
        const meta = get("runtimeMemoryMeta");
        if (!container || !meta) return;
        const items = payload && Array.isArray(payload.items) ? payload.items : [];
        const queryInfo = payload && payload.query && typeof payload.query === "object"
            ? payload.query
            : {};
        if (!Array.isArray(items) || items.length === 0) {
            meta.textContent = i18nFormat("runtime.total", { count: 0 });
            container.innerHTML = `<div class="empty-state">${t("runtime.empty")}</div>`;
            return;
        }
        const parts = [i18nFormat("runtime.total", { count: items.length })];
        const queryText = String(queryInfo.q || "").trim();
        if (queryText) parts.push(`q=${queryText}`);
        const topK = String(queryInfo.top_k || "").trim();
        if (topK) parts.push(`top_k=${topK}`);
        const timeFrom = String(queryInfo.time_from || "").trim();
        if (timeFrom) parts.push(`from=${timeFrom}`);
        const timeTo = String(queryInfo.time_to || "").trim();
        if (timeTo) parts.push(`to=${timeTo}`);
        meta.textContent = parts.join(" · ");
        container.innerHTML = items
            .map((item) => {
                const uuid = escapeHtml(item.uuid || "");
                const fact = escapeHtml(item.fact || "");
                const created = escapeHtml(item.created_at || "");
                return `<div class="runtime-list-item"><div class="runtime-list-head"><code>${uuid}</code><span>${created}</span></div><div class="runtime-list-fact">${fact}</div></div>`;
            })
            .join("");
    }

    function setListMessage(metaId, listId, message) {
        const meta = get(metaId);
        const list = get(listId);
        const msg = String(message || "").trim() || t("runtime.empty");
        if (meta) meta.textContent = msg;
        if (list) {
            list.innerHTML = `<div class="empty-state">${escapeHtml(msg)}</div>`;
        }
    }

    function renderCognitiveItems(metaId, listId, payload) {
        const meta = get(metaId);
        const list = get(listId);
        if (!meta || !list) return;
        const items = payload && Array.isArray(payload.items) ? payload.items : [];
        const count = Number.isFinite(Number(payload && payload.count))
            ? Number(payload.count)
            : items.length;
        meta.textContent = i18nFormat("runtime.total", { count });
        if (!items.length) {
            list.innerHTML = `<div class="empty-state">${t("runtime.empty")}</div>`;
            return;
        }

        const preferredMetaKeys = [
            "timestamp_local",
            "request_type",
            "group_id",
            "user_id",
            "sender_id",
            "entity_type",
            "entity_id",
            "request_id",
        ];

        list.innerHTML = items.map((item, index) => {
            const doc = escapeHtml(String((item && item.document) || "").trim());
            const md = item && typeof item.metadata === "object" && item.metadata
                ? item.metadata
                : {};
            const dist = formatNumeric(item && item.distance);
            const rerank = formatNumeric(item && item.rerank_score);
            const timestamp = escapeHtml(String(md.timestamp_local || "").trim());
            const headLabel = timestamp || `#${index + 1}`;
            const tags = [];
            if (dist) tags.push(`<span class="runtime-tag">distance ${dist}</span>`);
            if (rerank) tags.push(`<span class="runtime-tag">rerank ${rerank}</span>`);

            const metaRows = preferredMetaKeys
                .filter((key) => md[key] !== undefined && md[key] !== null && String(md[key]).trim() !== "")
                .map((key) => {
                    const raw = md[key];
                    const text = (raw && typeof raw === "object")
                        ? JSON.stringify(raw)
                        : String(raw);
                    return `<span class="runtime-kv-item"><span>${escapeHtml(key)}</span><code>${escapeHtml(text)}</code></span>`;
                })
                .join("");

            return `<div class="runtime-list-item">
                <div class="runtime-list-head"><span>${headLabel}</span><div class="runtime-tags">${tags.join("")}</div></div>
                <div class="runtime-doc">${doc || "--"}</div>
                ${metaRows ? `<div class="runtime-kv">${metaRows}</div>` : ""}
            </div>`;
        }).join("");
    }

    function renderProfileDetail(payload) {
        const meta = get("runtimeProfileMeta");
        const container = get("runtimeProfileResult");
        if (!meta || !container) return;
        if (!payload || typeof payload !== "object") {
            setListMessage("runtimeProfileMeta", "runtimeProfileResult", t("runtime.empty"));
            return;
        }

        const entityType = escapeHtml(String(payload.entity_type || "").trim());
        const entityId = escapeHtml(String(payload.entity_id || "").trim());
        const profileRaw = String(payload.profile || "").trim();
        const profile = renderStructuredText(profileRaw);
        const found = !!payload.found;
        const status = found ? t("runtime.found") : t("runtime.not_found");

        meta.textContent = `${entityType || "-"} / ${entityId || "-"} · ${status}`;
        container.innerHTML = `<div class="runtime-list-item">
            <div class="runtime-list-head"><code>${entityType || "-"}</code><code>${entityId || "-"}</code></div>
            <div class="runtime-doc">${profile || t("runtime.empty")}</div>
        </div>`;
    }

    function setProbeUnavailable(message) {
        const msg = String(message || RUNTIME_DISABLED_ERROR);
        setJsonBlock("runtimeProbeInternal", { error: msg });
        setJsonBlock("runtimeProbeExternal", { error: msg });
    }

    function setMemoryUnavailable(message) {
        const msg = String(message || RUNTIME_DISABLED_ERROR);
        setListMessage("runtimeMemoryMeta", "runtimeMemoryList", msg);
        setListMessage("runtimeEventsMeta", "runtimeEventsResult", msg);
        setListMessage("runtimeProfilesMeta", "runtimeProfilesResult", msg);
        setListMessage("runtimeProfileMeta", "runtimeProfileResult", msg);
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
        const query = readInputValue("runtimeMemoryQuery");
        const topK = readInputValue("runtimeMemoryTopK");
        const timeFrom = readInputValue("runtimeMemoryTimeFrom");
        const timeTo = readInputValue("runtimeMemoryTimeTo");
        const params = new URLSearchParams();
        appendQueryParam(params, "q", query);
        appendPositiveIntParam(params, "top_k", topK);
        appendQueryParam(params, "time_from", timeFrom);
        appendQueryParam(params, "time_to", timeTo);
        const data = await fetchJsonOrThrow(`/api/runtime/memory?${params.toString()}`);
        renderMemoryItems(data);
    }

    async function searchEvents() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage("runtimeEventsMeta", "runtimeEventsResult", t("runtime.disabled"));
            return;
        }
        const query = readInputValue("runtimeEventsQuery");
        if (!query) {
            setListMessage("runtimeEventsMeta", "runtimeEventsResult", "q is required");
            return;
        }
        const params = new URLSearchParams();
        appendQueryParam(params, "q", query);
        appendPositiveIntParam(params, "top_k", readInputValue("runtimeEventsTopK"));
        appendQueryParam(params, "request_type", readInputValue("runtimeEventsRequestType"));
        appendQueryParam(params, "target_user_id", readInputValue("runtimeEventsTargetUserId"));
        appendQueryParam(params, "target_group_id", readInputValue("runtimeEventsTargetGroupId"));
        appendQueryParam(params, "sender_id", readInputValue("runtimeEventsSenderId"));
        appendQueryParam(params, "time_from", readInputValue("runtimeEventsTimeFrom"));
        appendQueryParam(params, "time_to", readInputValue("runtimeEventsTimeTo"));
        const data = await fetchJsonOrThrow(`/api/runtime/cognitive/events?${params.toString()}`);
        renderCognitiveItems("runtimeEventsMeta", "runtimeEventsResult", data);
    }

    async function searchProfiles() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage("runtimeProfilesMeta", "runtimeProfilesResult", t("runtime.disabled"));
            return;
        }
        const query = readInputValue("runtimeProfilesQuery");
        if (!query) {
            setListMessage("runtimeProfilesMeta", "runtimeProfilesResult", "q is required");
            return;
        }
        const params = new URLSearchParams();
        appendQueryParam(params, "q", query);
        appendPositiveIntParam(params, "top_k", readInputValue("runtimeProfilesTopK"));
        appendQueryParam(params, "entity_type", readInputValue("runtimeProfilesEntityType"));
        const data = await fetchJsonOrThrow(`/api/runtime/cognitive/profiles?${params.toString()}`);
        renderCognitiveItems("runtimeProfilesMeta", "runtimeProfilesResult", data);
    }

    async function fetchProfileByEntity() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage("runtimeProfileMeta", "runtimeProfileResult", t("runtime.disabled"));
            return;
        }
        const entityType = readInputValue("runtimeProfileEntityType");
        const entityId = readInputValue("runtimeProfileEntityId");
        if (!entityType || !entityId) {
            setListMessage("runtimeProfileMeta", "runtimeProfileResult", "entity_type/entity_id are required");
            return;
        }
        const data = await fetchJsonOrThrow(`/api/runtime/cognitive/profile/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`);
        renderProfileDetail(data);
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
        const bindEnterMany = (ids, handler) => {
            ids.forEach((id) => bindEnter(id, handler));
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
        bindEnterMany(
            [
                "runtimeMemoryQuery",
                "runtimeMemoryTopK",
                "runtimeMemoryTimeFrom",
                "runtimeMemoryTimeTo",
            ],
            runMemorySearch
        );

        const eventsBtn = get("btnRuntimeEventsSearch");
        if (eventsBtn) eventsBtn.addEventListener("click", runEventsSearch);
        bindEnterMany(
            [
                "runtimeEventsQuery",
                "runtimeEventsTopK",
                "runtimeEventsTargetUserId",
                "runtimeEventsTargetGroupId",
                "runtimeEventsSenderId",
                "runtimeEventsTimeFrom",
                "runtimeEventsTimeTo",
            ],
            runEventsSearch
        );

        const profilesBtn = get("btnRuntimeProfilesSearch");
        if (profilesBtn) profilesBtn.addEventListener("click", runProfilesSearch);
        bindEnterMany(
            ["runtimeProfilesQuery", "runtimeProfilesTopK", "runtimeProfilesEntityType"],
            runProfilesSearch
        );

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
