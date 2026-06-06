(function () {
    const runtimeState = {
        initialized: false,
        probesLoaded: false,
        memoryLoaded: false,
        runtimeMetaLoaded: false,
        runtimeEnabled: true,
        chatBusy: false,
        chatConversationsLoaded: false,
        chatConversationsLoading: false,
        chatConversations: [],
        currentChatConversationId: "",
        activeJobConversationId: "",
        recentlyCreatedConversationId: "",
        chatHistoryLoaded: false,
        activeJobId: null,
        lastEventSeq: 0,
        chatHistoryCursor: null,
        chatHistoryHasMore: false,
        chatHistoryLoading: false,
        chatTopLoadSuppressedUntil: 0,
        chatAutoScroll: true,
        streamingMessageId: null,
        activeChatMessageId: null,
        chatPollTimer: null,
        chatPollBackoffMs: 500,
        chatClockTimer: null,
        activeJobResumeTimer: null,
        activeJobResumeAttempts: 0,
        toolBlocks: new Map(),
        toolCollapseTimers: new Map(),
        chatAttachments: [],
        chatAttachmentSeq: 0,
        chatReferences: [],
        chatReferenceSeq: 0,
        pendingSelectionReference: null,
        selectionQuoteButton: null,
        chatConversationDrawerOpen: false,
        htmlRunnerSource: "",
        htmlRunnerPickMode: false,
        htmlRunnerResize: null,
        htmlRunnerDrag: null,
        probeTimer: null,
        queryBusy: {
            memory: false,
            events: false,
            profiles: false,
            profileGet: false,
        },
    };
    const RUNTIME_DISABLED_ERROR = "Runtime API disabled";
    const CHAT_AUTO_SCROLL_STORAGE_KEY = "undefined_webchat_auto_scroll";
    const CHAT_POLL_INTERVAL_MS = 500;
    const CHAT_CLOCK_INTERVAL_MS = 500;
    const CHAT_TOP_LOAD_SUPPRESS_MS = 900;
    const TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS = 2000;
    const ACTIVE_JOB_RESUME_MAX_ATTEMPTS = 20;
    const CHAT_INLINE_IMAGE_MAX_BYTES = 12 * 1024 * 1024;
    const CHAT_ATTACHMENT_RAIL_BASE_WIDTH = 72;
    const CHAT_ATTACHMENT_RAIL_STEP_WIDTH = 56;
    const CHAT_ATTACHMENT_RAIL_MAX_WIDTH = 240;
    const CHAT_ATTACHMENT_CARD_MAX_WIDTH = 132;
    const CHAT_ATTACHMENT_CARD_MIN_WIDTH = 36;
    const CHAT_ATTACHMENT_GAP_WIDTH = 6;
    const CHAT_ATTACHMENT_COMPRESSED_GAP_WIDTH = 4;
    const CHAT_ATTACHMENT_COMPRESSED_COUNT = 5;
    const CHAT_REFERENCE_MAX_CHARS = 4000;
    const CHAT_REFERENCE_PREVIEW_CHARS = 180;
    const CODE_COLLAPSE_LINE_THRESHOLD = 8;
    const HTML_RUNNER_MIN_WIDTH = 360;
    const HTML_RUNNER_MIN_HEIGHT = 280;
    const HTML_RUNNER_VIEWPORT_MARGIN = 12;

    function prefersReducedMotion() {
        return (
            typeof window.matchMedia === "function" &&
            window.matchMedia("(prefers-reduced-motion: reduce)").matches
        );
    }

    function chatScrollBehavior() {
        return prefersReducedMotion() ? "auto" : "smooth";
    }

    function i18nFormat(key, params = {}) {
        let text = t(key);
        Object.keys(params).forEach((name) => {
            text = text.replaceAll(`{${name}}`, String(params[name]));
        });
        return text;
    }

    function currentChatConversationId() {
        return String(runtimeState.currentChatConversationId || "").trim();
    }

    function chatUrl(path, params = {}) {
        const query = new URLSearchParams();
        const conversationId = currentChatConversationId();
        if (conversationId) query.set("conversation_id", conversationId);
        Object.entries(params || {}).forEach(([key, value]) => {
            if (value === null || value === undefined || value === "") return;
            query.set(key, String(value));
        });
        const suffix = query.toString();
        return suffix ? `${path}?${suffix}` : path;
    }

    function runtimeChatJobEventsUrls(jobId, params) {
        const encoded = encodeURIComponent(jobId);
        const query = new URLSearchParams();
        const conversationId =
            runtimeState.activeJobConversationId || currentChatConversationId();
        if (conversationId) query.set("conversation_id", conversationId);
        Object.entries(params || {}).forEach(([key, value]) => {
            if (value === null || value === undefined || value === "") return;
            query.set(key, String(value));
        });
        const suffix = query.toString();
        return [
            `/api/v1/management/runtime/chat/jobs/${encoded}/events?${suffix}`,
            `/api/runtime/chat/jobs/${encoded}/events?${suffix}`,
        ];
    }

    function setJsonBlock(id, payload) {
        const el = get(id);
        if (!el) return;
        el.textContent = payload ? JSON.stringify(payload, null, 2) : "--";
    }

    /* ── Probe rendering helpers ── */

    function formatUptime(seconds) {
        if (!seconds || seconds < 0) return "--";
        const d = Math.floor(seconds / 86400);
        const h = Math.floor((seconds % 86400) / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        const parts = [];
        if (d > 0) parts.push(`${d}d`);
        if (h > 0) parts.push(`${h}h`);
        if (m > 0) parts.push(`${m}m`);
        parts.push(`${s}s`);
        return parts.join(" ");
    }

    function probeStatusBadge(status) {
        const cls =
            status === "ok" ? "ok" : status === "skipped" ? "skipped" : "error";
        const label =
            status === "ok" ? "OK" : status === "skipped" ? "Skipped" : "Error";
        return `<span class="probe-status ${cls}"><span class="probe-dot"></span>${escapeHtml(label)}</span>`;
    }

    function probeItem(label, value) {
        return `<div class="probe-item"><span class="probe-item-label">${escapeHtml(label)}</span><span class="probe-item-value">${value}</span></div>`;
    }

    function renderInternalProbe(data) {
        const el = get("runtimeProbeInternal");
        if (!el) return;
        if (!data || data.error) {
            el.innerHTML = `<div class="empty-state">${escapeHtml(data?.error || "--")}</div>`;
            return;
        }

        let html = "";

        // System info
        const ob = data.onebot || {};
        const obStatus = ob.connected ? "ok" : "error";
        html += `<div class="probe-section">`;
        html += `<div class="probe-section-title">${t("probes.section_system")}</div>`;
        html += `<div class="probe-grid">`;
        html += probeItem(
            t("probes.version"),
            `<code>v${escapeHtml(data.version || "--")}</code>`,
        );
        html += probeItem(
            "Python",
            `<code>${escapeHtml(data.python || "--")}</code>`,
        );
        html += probeItem(
            t("probes.platform"),
            escapeHtml(data.platform || "--"),
        );
        html += probeItem(
            t("probes.uptime"),
            `<code>${formatUptime(data.uptime_seconds)}</code>`,
        );
        html += probeItem("OneBot", probeStatusBadge(obStatus));
        if (ob.ws_url)
            html += probeItem(
                "WS URL",
                `<code>${escapeHtml(ob.ws_url)}</code>`,
            );
        html += `</div></div>`;

        // Models
        if (data.models && Object.keys(data.models).length > 0) {
            html += `<div class="probe-section">`;
            html += `<div class="probe-section-title">${t("probes.section_models")}</div>`;
            html += `<div class="probe-endpoint-list">`;
            for (const [key, m] of Object.entries(data.models)) {
                const label = key.replace(/_/g, " ");
                html += `<div class="probe-endpoint">`;
                html += `<div class="probe-endpoint-info">`;
                html += `<div class="probe-endpoint-name">${escapeHtml(label)}</div>`;
                html += `<div class="probe-endpoint-meta">`;
                if (m.model_name)
                    html += `<span>${t("probes.model")}: <code>${escapeHtml(m.model_name)}</code></span>`;
                if (m.api_url)
                    html += `<span>URL: <code>${escapeHtml(m.api_url)}</code></span>`;
                html += `</div></div>`;
                if (m.thinking_enabled !== undefined) {
                    html += `<div class="probe-endpoint-right"><span class="probe-queue-tag">${m.thinking_enabled ? "Thinking ✓" : "Thinking ✗"}</span></div>`;
                }
                html += `</div>`;
            }
            html += `</div></div>`;
        }

        // Queue
        const q = data.queues || {};
        if (q.totals || q.processor_count !== undefined) {
            html += `<div class="probe-section">`;
            html += `<div class="probe-section-title">${t("probes.section_queues")}</div>`;
            html += `<div class="probe-grid">`;
            if (q.processor_count !== undefined)
                html += probeItem(
                    t("probes.processors"),
                    String(q.processor_count),
                );
            if (q.inflight_count !== undefined)
                html += probeItem(
                    t("probes.inflight"),
                    String(q.inflight_count),
                );
            if (q.model_count !== undefined)
                html += probeItem(
                    t("probes.model_queues"),
                    String(q.model_count),
                );
            html += `</div>`;
            if (q.totals) {
                html += `<div class="probe-queue-row" style="margin-top:8px">`;
                for (const [k, v] of Object.entries(q.totals)) {
                    html += `<span class="probe-queue-tag"><span class="probe-queue-label">${escapeHtml(k)}</span> ${v}</span>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }

        // Message Batcher
        const mb = data.message_batcher || {};
        if (mb.config) {
            const cfg = mb.config || {};
            html += `<div class="probe-section">`;
            html += `<div class="probe-section-title">${t("probes.section_message_batcher")}</div>`;
            html += `<div class="probe-grid">`;
            html += probeItem(
                t("probes.batcher_enabled"),
                probeStatusBadge(cfg.enabled ? "ok" : "skipped"),
            );
            html += probeItem(
                t("probes.batcher_window"),
                `<code>${escapeHtml(String(cfg.window_seconds))}s</code>`,
            );
            html += probeItem(
                t("probes.batcher_strategy"),
                `<code>${escapeHtml(cfg.strategy || "")}</code>`,
            );
            html += probeItem(
                t("probes.batcher_pending"),
                String(mb.pending_buckets ?? 0),
            );
            html += probeItem(
                t("probes.batcher_group"),
                cfg.group_enabled ? "✓" : "✗",
            );
            html += probeItem(
                t("probes.batcher_private"),
                cfg.private_enabled ? "✓" : "✗",
            );
            html += probeItem(
                t("probes.batcher_speculative"),
                probeStatusBadge(cfg.speculative_enabled ? "ok" : "skipped"),
            );
            if (cfg.speculative_enabled) {
                html += probeItem(
                    t("probes.batcher_pre_send"),
                    `<code>${escapeHtml(String(cfg.pre_send_seconds))}s</code>`,
                );
            }
            html += `</div>`;
            const buckets = Array.isArray(mb.buckets) ? mb.buckets : [];
            if (buckets.length > 0) {
                html += `<div class="probe-queue-row" style="margin-top:8px">`;
                for (const b of buckets.slice(0, 10)) {
                    const label = `${escapeHtml(String(b.scope || ""))}/${escapeHtml(String(b.sender_id || ""))}`;
                    const phase = b.phase
                        ? ` ${escapeHtml(String(b.phase))}`
                        : "";
                    const inflight = b.has_inflight ? " ⚡" : "";
                    html += `<span class="probe-queue-tag"><span class="probe-queue-label">${label}</span> ${b.count}×@${b.elapsed_seconds}s${phase}${inflight}</span>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }

        // Memory & Cognitive
        const mem = data.memory || {};
        const cog = data.cognitive || {};
        html += `<div class="probe-section">`;
        html += `<div class="probe-section-title">${t("probes.section_services")}</div>`;
        html += `<div class="probe-grid">`;
        html += probeItem(t("probes.memory_count"), String(mem.count ?? "--"));
        html += probeItem(
            t("probes.cognitive"),
            probeStatusBadge(cog.enabled ? "ok" : "skipped"),
        );
        const apiInfo = data.api || {};
        html += probeItem(
            "Runtime API",
            probeStatusBadge(apiInfo.enabled ? "ok" : "error"),
        );
        if (apiInfo.enabled)
            html += probeItem(
                t("probes.api_listen"),
                `<code>${escapeHtml(apiInfo.host || "")}:${apiInfo.port || ""}</code>`,
            );
        html += `</div></div>`;

        // Skills
        const sk = data.skills || {};
        const skillRegs = [
            { key: "tools", label: t("probes.tools") },
            { key: "toolsets", label: t("probes.toolsets") },
            { key: "agents", label: t("probes.agents") },
            { key: "pipelines", label: t("probes.pipelines") },
            { key: "commands", label: t("probes.commands") },
            { key: "anthropic_skills", label: "Anthropic Skills" },
        ];
        if (skillRegs.some((reg) => sk[reg.key])) {
            html += `<div class="probe-section">`;
            html += `<div class="probe-section-title">${t("probes.section_skills")}</div>`;
            html += `<div class="probe-grid" style="margin-bottom:8px">`;
            for (const regMeta of skillRegs) {
                const reg = sk[regMeta.key];
                if (!reg) continue;
                html += probeItem(
                    regMeta.label,
                    `${reg.loaded ?? 0} / ${reg.count ?? 0}`,
                );
            }
            html += `</div>`;
            // Show active skills (ones with calls > 0)
            const activeItems = [];
            for (const { key } of skillRegs) {
                const reg = sk[key];
                if (reg && reg.items) {
                    for (const item of reg.items) {
                        if (item.calls > 0) activeItems.push(item);
                    }
                }
            }
            if (activeItems.length > 0) {
                activeItems.sort((a, b) => (b.calls || 0) - (a.calls || 0));
                const shown = activeItems.slice(0, 10);
                html += `<div style="display:grid;gap:4px">`;
                for (const item of shown) {
                    html += `<div class="probe-skill-row">`;
                    html += `<span class="probe-skill-name">${escapeHtml(item.name)}</span>`;
                    html += `<span class="probe-skill-stats">`;
                    html += `<span>${item.calls} calls</span>`;
                    html += `<span style="color:var(--success)">${item.success} ok</span>`;
                    if (item.failure > 0)
                        html += `<span style="color:var(--error)">${item.failure} fail</span>`;
                    html += `</span></div>`;
                }
                if (activeItems.length > 10) {
                    html += `<div class="muted-sm" style="text-align:center;padding:4px">+${activeItems.length - 10} more</div>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }

        el.innerHTML = html;
    }

    function renderExternalProbe(data) {
        const el = get("runtimeProbeExternal");
        if (!el) return;
        if (!data || data.error) {
            el.innerHTML = `<div class="empty-state">${escapeHtml(data?.error || "--")}</div>`;
            return;
        }

        let html = "";

        // Overall banner
        const allOk = data.ok;
        const bannerCls = allOk ? "ok" : "error";
        const bannerText = allOk ? t("probes.all_ok") : t("probes.some_failed");
        html += `<div class="probe-overall-banner ${bannerCls}"><span class="probe-dot" style="width:9px;height:9px;border-radius:50%;background:currentColor;flex-shrink:0"></span>${escapeHtml(bannerText)}</div>`;

        // Timestamp
        if (data.timestamp) {
            html += `<div class="muted-sm" style="margin-bottom:10px">${escapeHtml(data.timestamp)}</div>`;
        }

        // Endpoints
        const results = data.results || [];
        html += `<div class="probe-endpoint-list">`;
        for (const r of results) {
            const statusCls =
                r.status === "ok"
                    ? "ok"
                    : r.status === "skipped"
                      ? "skipped"
                      : "error";
            html += `<div class="probe-endpoint">`;
            html += `<div class="probe-endpoint-info">`;
            html += `<div class="probe-endpoint-name">${escapeHtml((r.name || "").replace(/_/g, " "))}</div>`;
            html += `<div class="probe-endpoint-meta">`;
            if (r.model_name)
                html += `<span>${t("probes.model")}: <code>${escapeHtml(r.model_name)}</code></span>`;
            if (r.url)
                html += `<span>URL: <code>${escapeHtml(r.url)}</code></span>`;
            if (r.host)
                html += `<span>Host: <code>${escapeHtml(r.host)}${r.port ? ":" + r.port : ""}</code></span>`;
            if (r.http_status) html += `<span>HTTP ${r.http_status}</span>`;
            if (r.error)
                html += `<span style="color:var(--error)">${escapeHtml(r.error)}</span>`;
            if (r.reason) html += `<span>${escapeHtml(r.reason)}</span>`;
            html += `</div></div>`;
            html += `<div class="probe-endpoint-right">`;
            html += probeStatusBadge(r.status);
            if (r.latency_ms !== undefined)
                html += `<span class="probe-latency">${r.latency_ms} ms</span>`;
            html += `</div></div>`;
        }
        html += `</div>`;

        el.innerHTML = html;
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

    function appendPositiveIntParam(params, key, value, max = 500) {
        const text = String(value || "").trim();
        if (!text) return;
        const num = Number.parseInt(text, 10);
        if (!Number.isFinite(num) || num <= 0) return;
        params.set(key, String(Math.min(num, max)));
    }

    function formatNumeric(value, digits = 4) {
        const num = Number(value);
        if (!Number.isFinite(num)) return "";
        return num.toFixed(digits);
    }

    function renderStructuredText(text) {
        const raw = String(text || "").trim();
        if (!raw) return escapeHtml(text || "");

        if (
            (raw.startsWith("{") && raw.endsWith("}")) ||
            (raw.startsWith("[") && raw.endsWith("]"))
        ) {
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
            blocks.push(
                `<ul class="runtime-profile-list">${listItems.join("")}</ul>`,
            );
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
                blocks.push(
                    `<div class="runtime-profile-title">${escapeHtml(heading[1])}</div>`,
                );
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
                    `<div class="runtime-profile-kv"><span class="runtime-profile-k">${escapeHtml(kv[1])}</span><span class="runtime-profile-v">${escapeHtml(kv[2])}</span></div>`,
                );
                continue;
            }

            flushList();
            blocks.push(
                `<p class="runtime-profile-p">${escapeHtml(textLine)}</p>`,
            );
        }
        flushList();
        return (
            blocks.join("") ||
            `<p class="runtime-profile-p">${escapeHtml(raw)}</p>`
        );
    }

    function hasMarkdownBlockquote(content) {
        return String(content || "")
            .split(/\r?\n/)
            .some((line) => /^\s*>/.test(line));
    }

    function shouldRenderChatMarkdown(role, content) {
        return role !== "user" || hasMarkdownBlockquote(content);
    }

    function appendChatMessage(role, content, options = {}) {
        const log = get("runtimeChatLog");
        if (!log) return null;
        const isBot = role !== "user";
        const useMarkdown = shouldRenderChatMarkdown(role, content);
        const contentClass = useMarkdown
            ? "runtime-chat-content markdown"
            : "runtime-chat-content";
        const item = document.createElement("div");
        item.className = `runtime-chat-item ${role}`;
        if (options.id) item.dataset.messageId = options.id;
        if (options.jobId) item.dataset.jobId = options.jobId;
        const roleHtml = isBot
            ? `<span class="runtime-chat-role-label">AI</span><span class="runtime-chat-stage" hidden></span>`
            : `<span class="runtime-chat-role-label">You</span>`;
        item.innerHTML = `<div class="runtime-chat-role">${roleHtml}</div><div class="${contentClass}">${renderChatContent(content, useMarkdown)}</div>`;
        if (isBot) {
            const roleEl = item.querySelector(".runtime-chat-role");
            if (roleEl) {
                const quoteButton = document.createElement("button");
                quoteButton.className = "runtime-chat-quote-btn";
                quoteButton.type = "button";
                quoteButton.dataset.quoteMessage = "1";
                quoteButton.textContent = t("runtime.quote");
                roleEl.appendChild(quoteButton);
            }
        }
        if (options.prepend) {
            log.insertBefore(item, log.firstChild);
        } else {
            log.appendChild(item);
            if (options.scroll !== false) scrollChatToBottom();
        }
        return item;
    }

    function formatDurationMs(value) {
        const ms = Number(value);
        if (!Number.isFinite(ms) || ms <= 0) return "";
        if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
        const seconds = ms / 1000;
        if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
        const minutes = Math.floor(seconds / 60);
        const remainder = Math.floor(seconds % 60);
        return `${minutes}m ${remainder}s`;
    }

    function messageQuoteSourceLabel(type) {
        if (type === "html") return t("runtime.reference_html");
        if (type === "selection") return t("runtime.reference_selection");
        return t("runtime.reference_message");
    }

    function scrollChatToBottom() {
        if (!runtimeState.chatAutoScroll) return;
        const log = get("runtimeChatLog");
        if (!log) return;
        suppressChatTopHistoryLoad();
        log.scrollTo({
            top: log.scrollHeight,
            behavior: chatScrollBehavior(),
        });
    }

    function forceScrollChatToBottom() {
        const log = get("runtimeChatLog");
        if (!log) return;
        suppressChatTopHistoryLoad();
        log.scrollTo({
            top: log.scrollHeight,
            behavior: chatScrollBehavior(),
        });
    }

    function suppressChatTopHistoryLoad() {
        runtimeState.chatTopLoadSuppressedUntil = Math.max(
            runtimeState.chatTopLoadSuppressedUntil || 0,
            Date.now() + CHAT_TOP_LOAD_SUPPRESS_MS,
        );
    }

    function isChatTopHistoryLoadSuppressed() {
        return Date.now() < (runtimeState.chatTopLoadSuppressedUntil || 0);
    }

    function forceScrollChatToBottomSoon() {
        suppressChatTopHistoryLoad();
        forceScrollChatToBottom();
        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(() => {
                forceScrollChatToBottom();
                requestAnimationFrame(forceScrollChatToBottom);
            });
        } else {
            setTimeout(forceScrollChatToBottom, 0);
        }
        setTimeout(forceScrollChatToBottom, 80);
        setTimeout(forceScrollChatToBottom, 260);
        setTimeout(forceScrollChatToBottom, 700);
    }

    function scrollChatToBottomSoon() {
        if (!runtimeState.chatAutoScroll) return;
        scrollChatToBottom();
        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(scrollChatToBottom);
            return;
        }
        setTimeout(scrollChatToBottom, 0);
    }

    function updateChatMessage(item, content, role = "bot") {
        if (!item) return;
        const contentEl = item.querySelector(".runtime-chat-content");
        if (!contentEl) return;
        const useMarkdown = shouldRenderChatMarkdown(role, content);
        contentEl.classList.toggle("markdown", useMarkdown);
        contentEl.innerHTML = renderChatContent(content, useMarkdown);
    }

    function currentChatJobId() {
        return runtimeState.activeJobId ? String(runtimeState.activeJobId) : "";
    }

    function findActiveChatMessage(jobId = "") {
        const byJob = String(jobId || "").trim();
        if (byJob) {
            const existingForJob = document.querySelector(
                `[data-job-id="${CSS.escape(byJob)}"]`,
            );
            if (existingForJob) return existingForJob;
        }
        if (runtimeState.activeChatMessageId) {
            const existing = document.querySelector(
                `[data-message-id="${CSS.escape(runtimeState.activeChatMessageId)}"]`,
            );
            if (existing) return existing;
        }
        if (runtimeState.streamingMessageId) {
            const existing = document.querySelector(
                `[data-message-id="${CSS.escape(runtimeState.streamingMessageId)}"]`,
            );
            if (existing) return existing;
        }
        return null;
    }

    function ensureStreamingMessage(jobId = "") {
        const resolvedJobId = String(jobId || currentChatJobId()).trim();
        const existing = findActiveChatMessage(resolvedJobId);
        if (existing) {
            if (resolvedJobId) existing.dataset.jobId = resolvedJobId;
            runtimeState.activeChatMessageId =
                existing.dataset.messageId || null;
            return existing;
        }
        const id = `stream-${Date.now()}`;
        runtimeState.streamingMessageId = id;
        runtimeState.activeChatMessageId = id;
        const item = appendChatMessage("bot", "", {
            id,
            jobId: resolvedJobId || null,
        });
        if (item) item.classList.add("streaming");
        return item;
    }

    function ensureTimelineNodeContainer(item) {
        if (!item) return null;
        let container = item.querySelector(".runtime-chat-timeline");
        if (!container) {
            container = document.createElement("div");
            container.className = "runtime-chat-timeline";
            const contentEl = item.querySelector(".runtime-chat-content");
            if (contentEl) contentEl.remove();
            item.appendChild(container);
        }
        return container;
    }

    function appendRawChatContent(item, content) {
        const text = String(content || "").trim();
        if (!item || !text) return;
        item.dataset.rawContent = [item.dataset.rawContent || "", text]
            .filter(Boolean)
            .join("\n\n");
    }

    function appendTimelineMessage(item, content, role = "bot") {
        const text = String(content || "").trim();
        if (!item || !text) return null;
        const timeline = ensureTimelineNodeContainer(item);
        if (!timeline) return null;
        const node = document.createElement("div");
        const useMarkdown = shouldRenderChatMarkdown(role, text);
        node.className = useMarkdown
            ? "runtime-chat-content markdown"
            : "runtime-chat-content";
        node.innerHTML = renderChatContent(text, useMarkdown);
        timeline.appendChild(node);
        appendRawChatContent(item, text);
        return node;
    }

    function renderHistoryAttachment(item) {
        if (!item || typeof item !== "object") return "";
        const mediaType = String(item.media_type || item.kind || "").trim();
        if (mediaType === "image") {
            const source = String(
                item.render_source || item.source_ref || "",
            ).trim();
            if (!source) return "";
            return `<img class="runtime-chat-image" src="${escapeHtml(source)}" alt="image" loading="lazy" />`;
        }
        const fileId = String(
            item.file_id || item.source_ref || item.uid || "",
        ).trim();
        if (!fileId) return "";
        return renderFileCard({
            id: fileId,
            name: item.display_name || item.name || fileId,
            size: item.size,
        });
    }

    function buildAttachmentMarkup(attachments) {
        const items = Array.isArray(attachments) ? attachments : [];
        return items
            .map((item) => renderHistoryAttachment(item))
            .filter(Boolean)
            .join("");
    }

    function readChatAutoScrollPreference() {
        try {
            const value = window.localStorage.getItem(
                CHAT_AUTO_SCROLL_STORAGE_KEY,
            );
            return value === null ? true : value !== "false";
        } catch (_error) {
            return true;
        }
    }

    function writeChatAutoScrollPreference(enabled) {
        try {
            window.localStorage.setItem(
                CHAT_AUTO_SCROLL_STORAGE_KEY,
                enabled ? "true" : "false",
            );
        } catch (_error) {
            // ignore storage failures in hardened browsers/private mode
        }
    }

    function syncChatAutoScrollToggle() {
        const input = get("runtimeChatAutoScroll");
        if (!input) return;
        input.checked = runtimeState.chatAutoScroll;
    }

    function setChatAutoScroll(enabled, { persist = true } = {}) {
        runtimeState.chatAutoScroll = !!enabled;
        syncChatAutoScrollToggle();
        if (persist) writeChatAutoScrollPreference(runtimeState.chatAutoScroll);
        if (runtimeState.chatAutoScroll) scrollChatToBottomSoon();
    }

    function clearToolCollapseTimers() {
        runtimeState.toolCollapseTimers.forEach((timer) => {
            clearTimeout(timer);
        });
        runtimeState.toolCollapseTimers.clear();
    }

    function refreshActiveChatTimers() {
        const item = findActiveChatMessage();
        if (item) {
            item.querySelectorAll(".runtime-chat-stage").forEach((stageEl) => {
                updateChatStageDisplay(stageEl);
            });
        }
        if (!runtimeState.toolBlocks.size) return;
        runtimeState.toolBlocks.forEach((block) => {
            if (!["done", "error", "cancelled"].includes(block.status)) {
                updateToolDurationDisplay(block);
            }
        });
    }

    function stopChatPolling() {
        clearTimeout(runtimeState.chatPollTimer);
        runtimeState.chatPollTimer = null;
    }

    function stopChatClock() {
        clearInterval(runtimeState.chatClockTimer);
        runtimeState.chatClockTimer = null;
    }

    function startChatClock() {
        if (runtimeState.chatClockTimer) return;
        runtimeState.chatClockTimer = setInterval(() => {
            refreshActiveChatTimers();
        }, CHAT_CLOCK_INTERVAL_MS);
    }

    function stopActiveJobResumeTimer() {
        clearTimeout(runtimeState.activeJobResumeTimer);
        runtimeState.activeJobResumeTimer = null;
    }

    function finishStreamingMessage() {
        if (!runtimeState.streamingMessageId) return;
        const item = document.querySelector(
            `[data-message-id="${CSS.escape(runtimeState.streamingMessageId)}"]`,
        );
        if (item) item.classList.remove("streaming");
        runtimeState.streamingMessageId = null;
    }

    function finalizeActiveChatMessage(payload = null) {
        const item = findActiveChatMessage();
        if (item) {
            const durationMs = Number(payload && payload.duration_ms);
            if (Number.isFinite(durationMs) && durationMs >= 0) {
                setChatStage(item, {
                    stage: "done",
                    elapsed_ms: durationMs,
                    final: true,
                });
            } else {
                setChatStage(item, null);
            }
        }
        finishStreamingMessage();
        runtimeState.activeChatMessageId = null;
        stopChatClock();
    }

    function chatStageLabel(stage) {
        const key = `runtime.chat_stage_${String(stage || "").trim()}`;
        const label = t(key);
        if (label !== key) return label;
        return String(stage || "").replace(/_/g, " ");
    }

    function setChatStage(item, payload) {
        if (!item) return;
        const stageEl = item.querySelector(".runtime-chat-stage");
        if (!stageEl) return;
        const stage = payload && payload.stage ? String(payload.stage) : "";
        if (!stage) {
            stageEl.hidden = true;
            stageEl.textContent = "";
            stageEl.removeAttribute("title");
            delete stageEl.dataset.stageLabel;
            delete stageEl.dataset.stageDetail;
            delete stageEl.dataset.stageBaseMs;
            delete stageEl.dataset.stageReceivedAtMs;
            stageEl.classList.remove("is-final");
            return;
        }
        const label = chatStageLabel(stage);
        const detail = String((payload && payload.detail) || "").trim();
        const elapsedMs = Number(payload && payload.elapsed_ms);
        const duration = Number.isFinite(elapsedMs) ? elapsedMs : 0;
        stageEl.hidden = false;
        stageEl.classList.toggle("is-final", !!(payload && payload.final));
        stageEl.dataset.stageLabel = label;
        stageEl.dataset.stageDetail = detail;
        stageEl.dataset.stageBaseMs = String(duration);
        stageEl.dataset.stageReceivedAtMs = String(monotonicNowMs());
        stageEl.title = detail ? `${label} · ${detail}` : label;
        updateChatStageDisplay(stageEl);
    }

    function updateChatStageDisplay(stageEl) {
        if (!stageEl || stageEl.hidden) return;
        const label = String(stageEl.dataset.stageLabel || "").trim();
        if (!label) return;
        const baseMs = Number(stageEl.dataset.stageBaseMs);
        const receivedAtMs = Number(stageEl.dataset.stageReceivedAtMs);
        const elapsedMs = stageEl.classList.contains("is-final")
            ? baseMs
            : baseMs + Math.max(0, monotonicNowMs() - receivedAtMs);
        const duration = formatDurationMs(elapsedMs);
        const nextText = duration ? `${label} · ${duration}` : label;
        if (stageEl.textContent !== nextText) {
            stageEl.textContent = nextText;
        }
    }

    function toolStatusLabel(block) {
        if (block.uiHint === "webchat_private_send") {
            return block.status === "done"
                ? t("runtime.sent")
                : block.status === "error"
                  ? t("runtime.error")
                  : t("runtime.sending");
        }
        if (block.uiHint === "webchat_end" && block.status === "done") {
            return t("runtime.ended");
        }
        if (block.status === "done") return t("runtime.done");
        if (block.status === "error") return t("runtime.error");
        if (block.status === "cancelled") return t("runtime.cancelled");
        return t("runtime.running");
    }

    function toolDisplayLabel(block) {
        if (block.uiHint === "webchat_private_send") {
            return t("runtime.message");
        }
        if (block.uiHint === "webchat_end") {
            return t("runtime.end");
        }
        return block.isAgent ? t("runtime.agent") : t("runtime.tool");
    }

    function formatToolPreview(raw) {
        const text = String(raw || "").trim();
        if (!text) return { text: "", isStructured: false, value: null };
        try {
            const parsed = JSON.parse(text);
            return {
                text,
                isStructured: parsed !== null && typeof parsed === "object",
                value: parsed,
            };
        } catch (_error) {
            try {
                const normalized = text
                    .replace(
                        /([{,]\s*)'([^'\\]*(?:\\.[^'\\]*)*)'\s*:/g,
                        '$1"$2":',
                    )
                    .replace(
                        /:\s*'([^'\\]*(?:\\.[^'\\]*)*)'(?=\s*[,}])/g,
                        ':"$1"',
                    )
                    .replace(
                        /([\[,]\s*)'([^'\\]*(?:\\.[^'\\]*)*)'(?=\s*[\],])/g,
                        '$1"$2"',
                    )
                    .replace(/\bNone\b/g, "null")
                    .replace(/\bTrue\b/g, "true")
                    .replace(/\bFalse\b/g, "false");
                const parsed = JSON.parse(normalized);
                return {
                    text,
                    isStructured: parsed !== null && typeof parsed === "object",
                    value: parsed,
                };
            } catch (_compatError) {
                return { text, isStructured: false, value: null };
            }
        }
    }

    function renderStructuredToolValue(value) {
        if (Array.isArray(value)) {
            if (!value.length) {
                return `<span class="runtime-tool-value muted">[]</span>`;
            }
            return (
                `<div class="runtime-tool-structured-list">` +
                value
                    .map(
                        (item, index) =>
                            `<div class="runtime-tool-structured-row">` +
                            `<span class="runtime-tool-key">${index}</span>` +
                            `<div class="runtime-tool-value">${renderStructuredToolValue(item)}</div>` +
                            `</div>`,
                    )
                    .join("") +
                `</div>`
            );
        }
        if (value && typeof value === "object") {
            const entries = Object.entries(value);
            if (!entries.length) {
                return `<span class="runtime-tool-value muted">{}</span>`;
            }
            return (
                `<div class="runtime-tool-structured-list">` +
                entries
                    .map(
                        ([key, item]) =>
                            `<div class="runtime-tool-structured-row">` +
                            `<span class="runtime-tool-key">${escapeHtml(key)}</span>` +
                            `<div class="runtime-tool-value">${renderStructuredToolValue(item)}</div>` +
                            `</div>`,
                    )
                    .join("") +
                `</div>`
            );
        }
        if (typeof value === "boolean") {
            return `<span class="runtime-tool-value boolean">${value ? "true" : "false"}</span>`;
        }
        if (typeof value === "number") {
            return `<span class="runtime-tool-value number">${escapeHtml(value)}</span>`;
        }
        if (value === null || value === undefined) {
            return `<span class="runtime-tool-value muted">null</span>`;
        }
        return `<span class="runtime-tool-value string">${renderChatContent(String(value), false)}</span>`;
    }

    function renderToolPreviewSection(labelKey, raw, options = {}) {
        const preview = formatToolPreview(raw);
        if (!preview.text) return "";
        const label = t(labelKey);
        const bodyClass = preview.isStructured
            ? "runtime-tool-preview-body is-structured"
            : "runtime-tool-preview-body";
        const body = preview.isStructured
            ? `<div class="${bodyClass}">${renderStructuredToolValue(preview.value)}</div>`
            : `<div class="${bodyClass}">${renderChatContent(preview.text, !!options.markdown)}</div>`;
        return (
            `<div class="runtime-tool-preview">` +
            `<div class="runtime-tool-preview-label">${escapeHtml(label)}</div>` +
            body +
            `</div>`
        );
    }

    function renderToolBlock(block) {
        const label = toolDisplayLabel(block);
        const statusLabel = toolStatusLabel(block);
        const durationLabel = formatDurationMs(runningDurationMs(block));
        const callId = toolCallIdentity(block);
        const stageLabel = block.currentStage
            ? chatStageLabel(block.currentStage)
            : "";
        const showLiveAgentStage =
            block.isAgent &&
            stageLabel &&
            !["done", "error", "cancelled"].includes(block.status);
        const metaLabel = showLiveAgentStage ? stageLabel : statusLabel;
        const titleHtml =
            `<span class="runtime-tool-title">` +
            `<code class="runtime-tool-name">${escapeHtml(block.name || "--")}</code>` +
            `<span class="runtime-tool-duration" data-tool-duration-for="${escapeHtml(callId)}"${durationLabel ? "" : " hidden"}>${escapeHtml(durationLabel)}</span>` +
            `</span>`;
        const args = renderToolPreviewSection(
            "runtime.tool_input",
            block.argumentsPreview,
            { markdown: false },
        );
        const result = renderToolPreviewSection(
            "runtime.tool_output",
            block.resultPreview,
            { markdown: true },
        );
        const timeline = Array.isArray(block.timeline)
            ? block.timeline.map(renderToolTimelineItem).join("")
            : "";
        const children =
            !timeline && Array.isArray(block.children)
                ? block.children.map((child) => renderToolBlock(child)).join("")
                : "";
        const childContent = timeline || children;
        const childHtml = childContent
            ? `<div class="runtime-tool-children">${childContent}</div>`
            : "";
        const openAttr = block.autoOpen ? " open" : "";
        const hintClass = block.uiHint
            ? ` ${escapeHtml(String(block.uiHint).replace(/_/g, "-"))}`
            : "";
        const kindClass = block.isAgent ? " is-agent" : " is-tool";
        return (
            `<details class="runtime-tool-block ${escapeHtml(block.status)}${kindClass}${hintClass}"${openAttr}>` +
            `<summary><span class="runtime-tool-summary-main">${titleHtml}</span><em class="runtime-tool-status" data-tool-status-for="${escapeHtml(callId)}">${escapeHtml(metaLabel)}</em><span class="runtime-tool-kind">${escapeHtml(label)}</span></summary>` +
            args +
            childHtml +
            result +
            `</details>`
        );
    }

    function renderToolTimelineItem(entry) {
        if (!entry || typeof entry !== "object") return "";
        if (entry.type === "message") {
            const content = String(entry.content || "").trim();
            if (!content) return "";
            return `<div class="runtime-tool-message">${renderChatContent(content, true)}</div>`;
        }
        if (entry.type === "stage") {
            return "";
        }
        if (entry.type === "call" && entry.call) {
            return renderToolBlock(entry.call);
        }
        return "";
    }

    function toolBlockKey(payload, blocks) {
        return (
            String(
                payload && payload.webchat_call_id
                    ? payload.webchat_call_id
                    : "",
            ) ||
            String(
                payload && payload.tool_call_id ? payload.tool_call_id : "",
            ) ||
            String(payload && payload.name ? payload.name : "") ||
            `tool-${blocks.size + 1}`
        );
    }

    function normalizeToolCallNode(node) {
        if (!node || typeof node !== "object") return null;
        const children = Array.isArray(node.children)
            ? node.children.map(normalizeToolCallNode).filter(Boolean)
            : [];
        const timeline = Array.isArray(node.timeline)
            ? node.timeline.map(normalizeHistoryTimelineNode).filter(Boolean)
            : [];
        return {
            name: String(node.name || ""),
            isAgent: !!node.is_agent,
            status: String(node.status || "done"),
            argumentsPreview: String(node.arguments_preview || ""),
            resultPreview: String(node.result_preview || ""),
            uiHint: String(node.ui_hint || ""),
            durationMs:
                node.duration_ms !== undefined
                    ? Number(node.duration_ms)
                    : undefined,
            currentStage: String(node.current_stage || ""),
            currentStageDetail: String(node.current_stage_detail || ""),
            currentStageElapsedMs:
                node.current_stage_elapsed_ms !== undefined
                    ? Number(node.current_stage_elapsed_ms)
                    : undefined,
            children,
            timeline,
            autoOpen: false,
        };
    }

    function normalizeHistoryTimelineNode(node) {
        if (!node || typeof node !== "object") return null;
        const type = String(node.type || "").trim();
        if (type === "message") {
            return {
                type,
                content: String(node.content || ""),
            };
        }
        if (type === "stage") {
            return {
                type,
                stage: String(node.stage || ""),
                detail: String(node.detail || ""),
                elapsedMs:
                    node.elapsed_ms !== undefined
                        ? Number(node.elapsed_ms)
                        : undefined,
                stageElapsedMs:
                    node.stage_elapsed_ms !== undefined
                        ? Number(node.stage_elapsed_ms)
                        : undefined,
            };
        }
        if (type === "call") {
            const call = normalizeToolCallNode(node.call);
            return call ? { type, call } : null;
        }
        return null;
    }

    function monotonicNowMs() {
        return typeof performance !== "undefined" &&
            typeof performance.now === "function"
            ? performance.now()
            : Date.now();
    }

    function backendDurationClock(payload, field = "duration_ms") {
        const durationMs = Number(payload && payload[field]);
        if (!Number.isFinite(durationMs) || durationMs < 0) return null;
        return {
            baseMs: durationMs,
            receivedAtMs: monotonicNowMs(),
        };
    }

    function runningDurationMs(block) {
        const baseMs = Number(block && block.durationBaseMs);
        const receivedAtMs = Number(block && block.durationReceivedAtMs);
        if (!Number.isFinite(baseMs) || baseMs < 0) {
            return Number(block && block.durationMs);
        }
        if (
            ["done", "error", "cancelled"].includes(String(block.status || ""))
        ) {
            return baseMs;
        }
        if (!Number.isFinite(receivedAtMs) || receivedAtMs <= 0) {
            return baseMs;
        }
        return Math.max(0, baseMs + monotonicNowMs() - receivedAtMs);
    }

    function updateToolDurationDisplay(block) {
        const identity = toolCallIdentity(block);
        if (!identity) return;
        const durationLabel = formatDurationMs(runningDurationMs(block));
        const selector = `[data-tool-duration-for="${CSS.escape(identity)}"]`;
        document.querySelectorAll(selector).forEach((node) => {
            if (node.textContent !== durationLabel) {
                node.textContent = durationLabel;
            }
            const nextHidden = !durationLabel;
            if (node.hidden !== nextHidden) {
                node.hidden = nextHidden;
            }
        });
    }

    function isToolLifecycleStart(status) {
        return status === "tool_start" || status === "agent_start";
    }

    function isToolLifecycleEnd(status) {
        return status === "tool_end" || status === "agent_end";
    }

    function reduceToolBlock(blocks, payload, status) {
        const key = toolBlockKey(payload, blocks);
        if (!blocks.has(key) && payload && payload.tool_call_id) {
            const nameKey = String(payload.name || "");
            if (nameKey && blocks.has(nameKey)) {
                blocks.set(key, blocks.get(nameKey));
                blocks.delete(nameKey);
            }
        }
        const previous = blocks.get(key) || {};
        const isStart = isToolLifecycleStart(status);
        const isEnd = isToolLifecycleEnd(status);
        const isSnapshot = status === "tool_snapshot";
        const durationClock = backendDurationClock(payload);
        const previousUiHint = String(previous.uiHint || "");
        const nextUiHint = String(
            (payload && payload.ui_hint) || previousUiHint,
        );
        const nextStatus = String((payload && payload.status) || "").trim();
        const nextArguments = String(
            (payload && payload.arguments_preview) ||
                previous.argumentsPreview ||
                "",
        );
        const block = {
            ...previous,
            webchatCallId: key,
            name: String((payload && payload.name) || previous.name || ""),
            isAgent: !!(
                (payload && payload.is_agent) ||
                previous.isAgent ||
                status === "agent_start" ||
                status === "agent_end"
            ),
            status:
                nextStatus ||
                (status === "tool_end" || status === "agent_end"
                    ? payload && payload.ok === false
                        ? "error"
                        : "done"
                    : "running"),
            argumentsPreview: nextArguments,
            resultPreview: String(
                (payload && payload.result_preview) ||
                    previous.resultPreview ||
                    "",
            ),
            uiHint: nextUiHint,
            durationMs:
                durationClock && isEnd
                    ? durationClock.baseMs
                    : payload && payload.duration_ms !== undefined
                      ? Number(payload.duration_ms)
                      : previous.durationMs,
            durationBaseMs:
                durationClock && (isSnapshot || isEnd)
                    ? durationClock.baseMs
                    : isStart
                      ? 0
                      : previous.durationBaseMs,
            durationReceivedAtMs:
                durationClock && (isSnapshot || isEnd)
                    ? durationClock.receivedAtMs
                    : isStart
                      ? monotonicNowMs()
                      : previous.durationReceivedAtMs,
            backendStartedAt: Number(
                (payload && payload.started_at) ||
                    previous.backendStartedAt ||
                    0,
            ),
            currentStage:
                isEnd && !(payload && payload.current_stage)
                    ? ""
                    : String(
                          (payload && payload.current_stage) ||
                              previous.currentStage ||
                              "",
                      ),
            currentStageDetail:
                isEnd && !(payload && payload.current_stage_detail)
                    ? ""
                    : String(
                          (payload && payload.current_stage_detail) ||
                              previous.currentStageDetail ||
                              "",
                      ),
            currentStageElapsedMs:
                isEnd && !(payload && payload.current_stage_elapsed_ms)
                    ? undefined
                    : payload && payload.current_stage_elapsed_ms !== undefined
                      ? Number(payload.current_stage_elapsed_ms)
                      : previous.currentStageElapsedMs,
            autoOpen: isStart || isSnapshot ? true : !!previous.autoOpen,
            localStartedAtMs: isStart
                ? monotonicNowMs()
                : previous.localStartedAtMs,
            finishedAtMs: isEnd ? monotonicNowMs() : previous.finishedAtMs,
            parentWebchatCallId: String(
                (payload && payload.parent_webchat_call_id) ||
                    previous.parentWebchatCallId ||
                    "",
            ),
            children: Array.isArray(previous.children) ? previous.children : [],
            timeline: Array.isArray(previous.timeline) ? previous.timeline : [],
        };
        blocks.set(key, block);
        return block;
    }

    function topLevelToolKey(blocks, key) {
        let currentKey = String(key || "").trim();
        const seen = new Set();
        while (currentKey && blocks.has(currentKey) && !seen.has(currentKey)) {
            seen.add(currentKey);
            const block = blocks.get(currentKey);
            const parentKey = String(block.parentWebchatCallId || "").trim();
            if (!parentKey || !blocks.has(parentKey)) return currentKey;
            currentKey = parentKey;
        }
        return currentKey || String(key || "");
    }

    function timelineToolKey(payload, blocks) {
        return toolBlockKey(payload, blocks);
    }

    function toolCallIdentity(block) {
        if (!block) return "";
        return String(block.webchatCallId || block.name || "").trim();
    }

    function toolRenderSignature(block) {
        if (!block) return "";
        return [
            block.webchatCallId,
            block.parentWebchatCallId,
            block.name,
            block.isAgent,
            block.status,
            block.argumentsPreview,
            block.resultPreview,
            block.uiHint,
            block.currentStage,
            block.currentStageDetail,
            Array.isArray(block.children) ? block.children.length : 0,
            Array.isArray(block.timeline) ? block.timeline.length : 0,
        ]
            .map((value) => String(value || ""))
            .join("\u001f");
    }

    function updateToolMetaDisplay(block) {
        if (!block) return;
        const identity = toolCallIdentity(block);
        if (!identity) return;
        updateToolDurationDisplay(block);
        const statusLabel = toolStatusLabel(block);
        const stageLabel = block.currentStage
            ? chatStageLabel(block.currentStage)
            : "";
        const showLiveAgentStage =
            block.isAgent &&
            stageLabel &&
            !["done", "error", "cancelled"].includes(block.status);
        const metaLabel = showLiveAgentStage ? stageLabel : statusLabel;
        const selector = `[data-tool-status-for="${CSS.escape(identity)}"]`;
        document.querySelectorAll(selector).forEach((node) => {
            if (node.textContent !== metaLabel) {
                node.textContent = metaLabel;
            }
        });
    }

    function renderToolNodeIfChanged(node, block) {
        if (!node || !block) return null;
        const nextSignature = toolRenderSignature(block);
        if (node.dataset.renderSignature === nextSignature) {
            updateToolMetaDisplay(block);
            return node;
        }
        node.innerHTML = renderToolBlock(block);
        node.dataset.renderSignature = nextSignature;
        return node;
    }

    function appendToolTimelineEntry(parent, entry) {
        if (!parent || !entry) return;
        const timeline = Array.isArray(parent.timeline) ? parent.timeline : [];
        if (entry.type === "call" && entry.call) {
            const identity = toolCallIdentity(entry.call);
            const existingIndex = timeline.findIndex(
                (item) =>
                    item.type === "call" &&
                    toolCallIdentity(item.call) === identity,
            );
            if (existingIndex >= 0) {
                timeline[existingIndex] = entry;
            } else {
                timeline.push(entry);
            }
            parent.timeline = timeline;
            return;
        }
        if (entry.type === "stage") {
            const entrySeq = Number(entry.seq);
            const existingIndex = timeline.findIndex(
                (item) =>
                    item.type === "stage" &&
                    Number(item.seq) === entrySeq &&
                    String(item.stage || "") === String(entry.stage || ""),
            );
            if (existingIndex >= 0) {
                timeline[existingIndex] = entry;
            } else {
                timeline.push(entry);
            }
            parent.timeline = timeline;
            return;
        }
        timeline.push(entry);
        parent.timeline = timeline;
    }

    function reduceAgentStageBlock(blocks, payload, seq = 0) {
        const key = toolBlockKey(payload, blocks);
        const previous = blocks.get(key) || {};
        const parentCandidate = String(
            (payload && payload.parent_webchat_call_id) ||
                previous.parentWebchatCallId ||
                "",
        ).trim();
        const parentKey = parentCandidate === key ? "" : parentCandidate;
        const stage = String((payload && payload.stage) || "").trim();
        const block = {
            ...previous,
            webchatCallId: key,
            name: String(
                (payload && (payload.agent_name || payload.name)) ||
                    previous.name ||
                    "",
            ),
            isAgent: true,
            status: String(
                (payload && payload.status) || previous.status || "running",
            ),
            argumentsPreview: previous.argumentsPreview || "",
            resultPreview: previous.resultPreview || "",
            uiHint: previous.uiHint || "",
            currentStage: stage || previous.currentStage || "",
            currentStageDetail: String(
                (payload && payload.detail) ||
                    previous.currentStageDetail ||
                    "",
            ),
            currentStageElapsedMs:
                payload && payload.stage_elapsed_ms !== undefined
                    ? Number(payload.stage_elapsed_ms)
                    : previous.currentStageElapsedMs,
            durationMs: previous.durationMs,
            durationBaseMs: previous.durationBaseMs,
            durationReceivedAtMs: previous.durationReceivedAtMs,
            backendStartedAt: previous.backendStartedAt,
            autoOpen: !!previous.autoOpen,
            parentWebchatCallId: parentKey,
            children: Array.isArray(previous.children) ? previous.children : [],
            timeline: Array.isArray(previous.timeline) ? previous.timeline : [],
        };
        blocks.set(key, block);
        return block;
    }

    function agentStageRenderSignature(block) {
        if (!block) return "";
        return [
            block.webchatCallId,
            block.parentWebchatCallId,
            block.name,
            block.status,
            block.currentStage,
            block.currentStageDetail,
        ]
            .map((value) => String(value || ""))
            .join("\u001f");
    }

    function redrawToolTimelineNode(item, blocks, key) {
        const timeline = ensureTimelineNodeContainer(item);
        if (!timeline) return null;
        const rootKey = topLevelToolKey(blocks, key);
        const root = blocks.get(rootKey);
        if (!root) return null;
        let node = timeline.querySelector(
            `[data-tool-key="${CSS.escape(rootKey)}"]`,
        );
        if (!node) {
            node = document.createElement("div");
            node.className = "runtime-chat-tools";
            node.dataset.toolKey = rootKey;
            timeline.appendChild(node);
        }
        return renderToolNodeIfChanged(node, root);
    }

    function scheduleToolAutoCollapse(item, blocks, key, block) {
        if (!item || !block || block.status === "running") return;
        const timerKey = String(key || "").trim();
        if (!timerKey) return;
        if (runtimeState.toolCollapseTimers.has(timerKey)) {
            clearTimeout(runtimeState.toolCollapseTimers.get(timerKey));
            runtimeState.toolCollapseTimers.delete(timerKey);
        }
        const collapse = () => {
            runtimeState.toolCollapseTimers.delete(timerKey);
            const latest = blocks.get(timerKey);
            if (!latest) return;
            latest.autoOpen = false;
            redrawToolTimelineNode(item, blocks, timerKey);
        };
        runtimeState.toolCollapseTimers.set(
            timerKey,
            setTimeout(collapse, TOOL_AUTO_COLLAPSE_MIN_VISIBLE_MS),
        );
    }

    function upsertTimelineToolBlock(item, blocks, payload, status) {
        if (!item) return null;
        const key = timelineToolKey(payload, blocks);
        const previousRootKey = topLevelToolKey(blocks, key);
        const previousRoot = blocks.get(previousRootKey);
        const previousSignature = toolRenderSignature(previousRoot);
        const block = reduceToolBlock(blocks, payload, status);
        const timeline = ensureTimelineNodeContainer(item);
        if (!timeline) return null;
        const parentKey = String(
            (payload && payload.parent_webchat_call_id) || "",
        ).trim();
        if (parentKey && blocks.has(parentKey)) {
            const parent = blocks.get(parentKey);
            const previousParentSignature = toolRenderSignature(parent);
            const blockIdentity = toolCallIdentity(block);
            const siblings = Array.isArray(parent.children)
                ? parent.children.filter(
                      (child) => toolCallIdentity(child) !== blockIdentity,
                  )
                : [];
            parent.children = [...siblings, block];
            appendToolTimelineEntry(parent, { type: "call", call: block });
            const nextParentSignature = toolRenderSignature(parent);
            const parentNode = timeline.querySelector(
                `[data-tool-key="${CSS.escape(parentKey)}"]`,
            );
            if (parentNode) {
                if (
                    status === "tool_snapshot" &&
                    previousParentSignature === nextParentSignature
                ) {
                    updateToolMetaDisplay(block);
                    updateToolMetaDisplay(parent);
                    return parentNode;
                }
                renderToolNodeIfChanged(parentNode, parent);
                if (isToolLifecycleEnd(status)) {
                    scheduleToolAutoCollapse(item, blocks, key, block);
                }
                return parentNode;
            }
            const rootKey = topLevelToolKey(blocks, parentKey);
            const root = blocks.get(rootKey);
            const rootNode = timeline.querySelector(
                `[data-tool-key="${CSS.escape(rootKey)}"]`,
            );
            if (root && rootNode) {
                const previousRootSignature =
                    rootNode.dataset.renderSignature ||
                    toolRenderSignature(root);
                const nextRootSignature = toolRenderSignature(root);
                if (
                    status === "tool_snapshot" &&
                    previousRootSignature === nextRootSignature
                ) {
                    updateToolMetaDisplay(block);
                    updateToolMetaDisplay(root);
                    return rootNode;
                }
                renderToolNodeIfChanged(rootNode, root);
                if (isToolLifecycleEnd(status)) {
                    scheduleToolAutoCollapse(item, blocks, key, block);
                }
                return rootNode;
            }
        }
        let node = timeline.querySelector(
            `[data-tool-key="${CSS.escape(key)}"]`,
        );
        if (!node) {
            node = document.createElement("div");
            node.className = "runtime-chat-tools";
            node.dataset.toolKey = key;
            timeline.appendChild(node);
        }
        if (status === "tool_snapshot" && previousSignature) {
            const nextSignature = toolRenderSignature(block);
            if (previousSignature === nextSignature) {
                updateToolMetaDisplay(block);
                return node;
            }
        }
        renderToolNodeIfChanged(node, block);
        if (isToolLifecycleEnd(status)) {
            scheduleToolAutoCollapse(item, blocks, key, block);
        }
        return node;
    }

    function appendNestedTimelineMessage(item, blocks, payload, content) {
        const parentKey = String(
            (payload && payload.parent_webchat_call_id) || "",
        ).trim();
        if (!parentKey || !blocks.has(parentKey)) return false;
        const parent = blocks.get(parentKey);
        appendToolTimelineEntry(parent, {
            type: "message",
            content,
        });
        redrawToolTimelineNode(item, blocks, parentKey);
        appendRawChatContent(item, content);
        return true;
    }

    function upsertToolBlock(payload, status, jobId = "") {
        const item = ensureStreamingMessage(jobId);
        if (!item) return;
        upsertTimelineToolBlock(item, runtimeState.toolBlocks, payload, status);
        scrollChatToBottomSoon();
    }

    function upsertToolSnapshot(payload, jobId = "") {
        const item = ensureStreamingMessage(jobId);
        if (!item) return;
        upsertTimelineToolBlock(
            item,
            runtimeState.toolBlocks,
            payload,
            "tool_snapshot",
        );
    }

    function upsertAgentStageBlock(payload, jobId = "", seq = 0) {
        const item = ensureStreamingMessage(jobId);
        if (!item) return;
        const blocks = runtimeState.toolBlocks;
        const key = timelineToolKey(payload, blocks);
        const previousSignature = agentStageRenderSignature(blocks.get(key));
        const block = reduceAgentStageBlock(blocks, payload, seq);
        if (
            previousSignature &&
            previousSignature === agentStageRenderSignature(block)
        ) {
            return;
        }
        const parentKey = String(block.parentWebchatCallId || "").trim();
        const timeline = ensureTimelineNodeContainer(item);
        if (!timeline) return;
        if (parentKey && blocks.has(parentKey)) {
            const parent = blocks.get(parentKey);
            const previousParentSignature = toolRenderSignature(parent);
            const blockIdentity = toolCallIdentity(block);
            const siblings = Array.isArray(parent.children)
                ? parent.children.filter(
                      (child) => toolCallIdentity(child) !== blockIdentity,
                  )
                : [];
            parent.children = [...siblings, block];
            appendToolTimelineEntry(parent, { type: "call", call: block });
            const nextParentSignature = toolRenderSignature(parent);
            if (previousParentSignature === nextParentSignature) {
                updateToolMetaDisplay(block);
                updateToolMetaDisplay(parent);
            } else {
                redrawToolTimelineNode(item, blocks, parentKey);
            }
        } else {
            let node = timeline.querySelector(
                `[data-tool-key="${CSS.escape(key)}"]`,
            );
            if (!node) {
                node = document.createElement("div");
                node.className = "runtime-chat-tools";
                node.dataset.toolKey = key;
                timeline.appendChild(node);
            }
            renderToolNodeIfChanged(node, block);
        }
        scrollChatToBottomSoon();
    }

    function historyWebchatEvents(item) {
        const webchat = item && item.webchat;
        const events =
            webchat && Array.isArray(webchat.events) ? webchat.events : [];
        return events.filter((entry) => {
            const event = entry && String(entry.event || "");
            return (
                event === "tool_start" ||
                event === "tool_end" ||
                event === "agent_start" ||
                event === "agent_end" ||
                event === "agent_stage" ||
                event === "message"
            );
        });
    }

    function renderHistoryTimeline(item, message) {
        const events = historyWebchatEvents(item);
        if (!message || !events.length) return false;
        const calls =
            item && item.webchat && Array.isArray(item.webchat.calls)
                ? item.webchat.calls
                : [];
        const timelineItems =
            item && item.webchat && Array.isArray(item.webchat.timeline)
                ? item.webchat.timeline
                : [];
        if (timelineItems.length) {
            const timeline = ensureTimelineNodeContainer(message);
            if (timeline) {
                timelineItems
                    .map(normalizeHistoryTimelineNode)
                    .filter(Boolean)
                    .forEach((entry, index) => {
                        if (entry.type === "message") {
                            appendTimelineMessage(
                                message,
                                entry.content,
                                "bot",
                            );
                            return;
                        }
                        if (entry.type !== "call" || !entry.call) return;
                        const node = document.createElement("div");
                        node.className = "runtime-chat-tools";
                        node.dataset.toolKey = `history-call-${index}`;
                        node.innerHTML = renderToolBlock(entry.call);
                        timeline.appendChild(node);
                    });
            }
            return true;
        }
        if (calls.length) {
            const timeline = ensureTimelineNodeContainer(message);
            if (timeline) {
                calls
                    .map(normalizeToolCallNode)
                    .filter(Boolean)
                    .forEach((block, index) => {
                        const node = document.createElement("div");
                        node.className = "runtime-chat-tools";
                        node.dataset.toolKey = `history-call-${index}`;
                        node.innerHTML = renderToolBlock(block);
                        timeline.appendChild(node);
                    });
            }
            events
                .filter((entry) => entry.event === "message")
                .forEach((entry) => {
                    appendTimelineMessage(
                        message,
                        entry.payload &&
                            (entry.payload.content ?? entry.payload.message),
                        "bot",
                    );
                });
            return true;
        }
        const blocks = new Map();
        events.forEach((entry) => {
            if (entry.event === "message") {
                appendTimelineMessage(
                    message,
                    entry.payload &&
                        (entry.payload.content ?? entry.payload.message),
                    "bot",
                );
                return;
            }
            upsertTimelineToolBlock(
                message,
                blocks,
                entry.payload || {},
                entry.event,
            );
        });
        return true;
    }

    function appendHistoryChatItem(item, options = {}) {
        const role = item && item.role === "bot" ? "bot" : "user";
        const content = String((item && item.content) || "").trim();
        const attachmentMarkup = buildAttachmentMarkup(
            item && item.attachments,
        );
        const hasTimeline =
            role === "bot" && historyWebchatEvents(item).length > 0;
        if (!content && !hasTimeline && !attachmentMarkup) return null;
        const message = appendChatMessage(role, content, options);
        if (!message) return null;
        if (hasTimeline) {
            const contentEl = message.querySelector(".runtime-chat-content");
            if (contentEl) contentEl.innerHTML = "";
            renderHistoryTimeline(item, message);
            if (!message.dataset.rawContent && content) {
                appendTimelineMessage(message, content, role);
            }
        }
        if (attachmentMarkup) {
            const contentEl = message.querySelector(".runtime-chat-content");
            if (contentEl) {
                contentEl.insertAdjacentHTML("beforeend", attachmentMarkup);
            }
        }
        const webchat = item && item.webchat;
        const durationMs = Number(webchat && webchat.duration_ms);
        if (role === "bot" && Number.isFinite(durationMs) && durationMs >= 0) {
            setChatStage(message, {
                stage: "done",
                elapsed_ms: durationMs,
                final: true,
            });
        }
        if (!content && !attachmentMarkup && !message.dataset.rawContent) {
            message.classList.add("tool-only");
        }
        return message;
    }

    function clearChatMessages() {
        const log = get("runtimeChatLog");
        if (!log) return;
        clearToolCollapseTimers();
        log.innerHTML = "";
        runtimeState.streamingMessageId = null;
        runtimeState.activeChatMessageId = null;
        runtimeState.toolBlocks.clear();
        stopChatClock();
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
        if (raw.startsWith("file://")) {
            const localPath = raw.slice("file://".length).trim();
            return localPath
                ? `/api/runtime/chat/image?path=${encodeURIComponent(localPath)}`
                : "";
        }
        if (raw.startsWith("/") || /^[A-Za-z]:[\\/]/.test(raw)) {
            return `/api/runtime/chat/image?path=${encodeURIComponent(raw)}`;
        }
        if (
            raw.startsWith("http://") ||
            raw.startsWith("https://") ||
            raw.startsWith("data:image/")
        ) {
            return raw;
        }
        return "";
    }

    function formatFileSize(bytes) {
        const n = Number(bytes);
        if (!Number.isFinite(n) || n <= 0) return "";
        if (n < 1024) return n + "B";
        if (n < 1024 * 1024) return (n / 1024).toFixed(1) + "KB";
        return (n / 1024 / 1024).toFixed(2) + "MB";
    }

    function fileKind(file) {
        const type = String((file && file.type) || "").toLowerCase();
        return type.startsWith("image/") ? "image" : "file";
    }

    function formatAttachmentName(file) {
        return (
            String((file && file.name) || "attachment").trim() || "attachment"
        );
    }

    function renderPendingChatAttachments() {
        const container = get("runtimeChatAttachments");
        if (!container) return;
        const inputRow = container.closest(".runtime-chat-input-row");
        if (!runtimeState.chatAttachments.length) {
            container.hidden = true;
            container.innerHTML = "";
            if (inputRow) {
                inputRow.classList.remove(
                    "has-attachments",
                    "is-attachment-rail-full",
                    "is-attachment-compressed",
                );
                inputRow.style.setProperty(
                    "--chat-attachment-rail-width",
                    "0px",
                );
                inputRow.style.setProperty(
                    "--chat-attachment-card-width",
                    `${CHAT_ATTACHMENT_CARD_MAX_WIDTH}px`,
                );
            }
            return;
        }
        container.hidden = false;
        if (inputRow) {
            const count = runtimeState.chatAttachments.length;
            const width = Math.min(
                CHAT_ATTACHMENT_RAIL_MAX_WIDTH,
                CHAT_ATTACHMENT_RAIL_BASE_WIDTH +
                    count * CHAT_ATTACHMENT_RAIL_STEP_WIDTH,
            );
            const gapWidth =
                count >= CHAT_ATTACHMENT_COMPRESSED_COUNT
                    ? CHAT_ATTACHMENT_COMPRESSED_GAP_WIDTH
                    : CHAT_ATTACHMENT_GAP_WIDTH;
            const cardWidth = Math.max(
                CHAT_ATTACHMENT_CARD_MIN_WIDTH,
                Math.min(
                    CHAT_ATTACHMENT_CARD_MAX_WIDTH,
                    Math.floor(
                        (width - Math.max(0, count - 1) * gapWidth) / count,
                    ),
                ),
            );
            inputRow.classList.toggle("has-attachments", count > 0);
            inputRow.classList.toggle(
                "is-attachment-rail-full",
                width >= CHAT_ATTACHMENT_RAIL_MAX_WIDTH,
            );
            inputRow.classList.toggle(
                "is-attachment-compressed",
                count >= CHAT_ATTACHMENT_COMPRESSED_COUNT,
            );
            inputRow.style.setProperty(
                "--chat-attachment-rail-width",
                `${width}px`,
            );
            inputRow.style.setProperty(
                "--chat-attachment-card-width",
                `${cardWidth}px`,
            );
        }
        container.innerHTML = runtimeState.chatAttachments
            .map((item) => {
                const kindLabel =
                    item.kind === "image"
                        ? t("runtime.attachment_kind_image")
                        : t("runtime.attachment_kind_file");
                const preview = item.previewUrl
                    ? `<img class="runtime-chat-attachment-thumb" src="${escapeHtml(item.previewUrl)}" alt="" loading="lazy" onerror="this.closest('.runtime-chat-attachment-preview')?.classList.add('is-missing-thumb'); this.remove();" />`
                    : `<span class="runtime-chat-attachment-file" aria-hidden="true">${item.kind === "image" ? "IMG" : "FILE"}</span>`;
                return (
                    `<div class="runtime-chat-attachment" data-attachment-id="${escapeHtml(item.id)}">` +
                    `<span class="runtime-chat-attachment-preview">${preview}</span>` +
                    `<span class="runtime-chat-attachment-main">` +
                    `<span class="runtime-chat-attachment-name">${escapeHtml(item.name)}</span>` +
                    `<span class="runtime-chat-attachment-meta">${escapeHtml(kindLabel)}${item.sizeLabel ? ` · ${escapeHtml(item.sizeLabel)}` : ""}</span>` +
                    `</span>` +
                    `<button class="runtime-chat-attachment-remove" type="button" data-attachment-remove="${escapeHtml(item.id)}" aria-label="${escapeHtml(t("runtime.remove_attachment"))}">×</button>` +
                    `</div>`
                );
            })
            .join("");
        container
            .querySelectorAll("[data-attachment-remove]")
            .forEach((button) => {
                button.addEventListener("click", () => {
                    const id = String(
                        button.getAttribute("data-attachment-remove") || "",
                    );
                    const removed = runtimeState.chatAttachments.find(
                        (item) => item.id === id,
                    );
                    if (removed && removed.previewUrl) {
                        URL.revokeObjectURL(removed.previewUrl);
                    }
                    runtimeState.chatAttachments =
                        runtimeState.chatAttachments.filter(
                            (item) => item.id !== id,
                        );
                    renderPendingChatAttachments();
                });
            });
    }

    function addChatFiles(files, { source = "picker" } = {}) {
        const selected = Array.from(files || []).filter(Boolean);
        if (!selected.length) return 0;
        const added = [];
        for (const file of selected) {
            const name = formatAttachmentName(file);
            const size = Number(file.size || 0);
            const kind = fileKind(file);
            added.push({
                id: `att-${Date.now()}-${runtimeState.chatAttachmentSeq++}`,
                file,
                kind,
                name,
                previewUrl: kind === "image" ? URL.createObjectURL(file) : "",
                size,
                sizeLabel: formatFileSize(size),
                source,
            });
        }
        runtimeState.chatAttachments.push(...added);
        renderPendingChatAttachments();
        const messageKey =
            added.length === 1
                ? "runtime.attachment_added"
                : "runtime.attachments_added";
        showToast(
            i18nFormat(messageKey, { count: added.length }),
            "success",
            1800,
        );
        return added.length;
    }

    function clearChatAttachments() {
        runtimeState.chatAttachments.forEach((item) => {
            if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        });
        runtimeState.chatAttachments = [];
        renderPendingChatAttachments();
    }

    function normalizeReferenceText(text) {
        return String(text || "")
            .replace(/\r\n?/g, "\n")
            .replace(/\n{4,}/g, "\n\n\n")
            .trim();
    }

    function truncateReferenceText(text, maxChars = CHAT_REFERENCE_MAX_CHARS) {
        const value = normalizeReferenceText(text);
        if (value.length <= maxChars) return value;
        return `${value.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
    }

    function referencePreview(text) {
        const value = normalizeReferenceText(text).replace(/\s+/g, " ");
        if (value.length <= CHAT_REFERENCE_PREVIEW_CHARS) return value;
        return `${value.slice(0, CHAT_REFERENCE_PREVIEW_CHARS - 1).trimEnd()}…`;
    }

    function renderPendingChatReferences() {
        const container = get("runtimeChatReferences");
        if (!container) return;
        if (!runtimeState.chatReferences.length) {
            container.hidden = true;
            container.innerHTML = "";
            return;
        }
        container.hidden = false;
        container.innerHTML = runtimeState.chatReferences
            .map((item) => {
                const label = messageQuoteSourceLabel(item.type);
                const preview = referencePreview(item.text);
                return (
                    `<div class="runtime-chat-reference" data-reference-id="${escapeHtml(item.id)}">` +
                    `<span class="runtime-chat-reference-mark">“</span>` +
                    `<span class="runtime-chat-reference-main">` +
                    `<span class="runtime-chat-reference-label">${escapeHtml(label)}</span>` +
                    `<span class="runtime-chat-reference-text">${escapeHtml(preview)}</span>` +
                    `</span>` +
                    `<button class="runtime-chat-reference-remove" type="button" data-reference-remove="${escapeHtml(item.id)}" aria-label="${escapeHtml(t("runtime.remove_reference"))}">×</button>` +
                    `</div>`
                );
            })
            .join("");
        container
            .querySelectorAll("[data-reference-remove]")
            .forEach((button) => {
                button.addEventListener("click", () => {
                    const id = String(
                        button.getAttribute("data-reference-remove") || "",
                    );
                    runtimeState.chatReferences =
                        runtimeState.chatReferences.filter(
                            (item) => item.id !== id,
                        );
                    renderPendingChatReferences();
                });
            });
    }

    function addChatReference({ type = "message", text = "" } = {}) {
        const value = truncateReferenceText(text);
        if (!value) return false;
        runtimeState.chatReferences.push({
            id: `ref-${Date.now()}-${runtimeState.chatReferenceSeq++}`,
            type,
            text: value,
        });
        renderPendingChatReferences();
        showToast(t("runtime.reference_added"), "success", 1600);
        const input = get("runtimeChatInput");
        if (input) input.focus();
        return true;
    }

    function clearChatReferences() {
        runtimeState.chatReferences = [];
        renderPendingChatReferences();
    }

    function formatChatReferencesAsMarkdown(references) {
        const items = Array.isArray(references) ? references : [];
        if (!items.length) return "";
        return items
            .map((item) => {
                const label = messageQuoteSourceLabel(item.type);
                const lines = normalizeReferenceText(item.text).split("\n");
                return [`> ${label}:`, ...lines.map((line) => `> ${line}`)]
                    .join("\n")
                    .trim();
            })
            .filter(Boolean)
            .join("\n\n");
    }

    function buildChatMessageWithReferences(message, references) {
        const quote = formatChatReferencesAsMarkdown(references);
        const body = String(message || "").trim();
        return [quote, body].filter(Boolean).join("\n\n").trim();
    }

    function chatMessageTextForQuote(item) {
        if (!item) return "";
        const raw = String(item.dataset.rawContent || "").trim();
        if (raw) return raw;
        const content = item.querySelector(".runtime-chat-content");
        if (content) return normalizeReferenceText(content.innerText || "");
        const timeline = item.querySelector(".runtime-chat-timeline");
        return timeline ? normalizeReferenceText(timeline.innerText || "") : "";
    }

    function hideSelectionQuoteButton() {
        if (runtimeState.selectionQuoteButton) {
            runtimeState.selectionQuoteButton.hidden = true;
        }
        runtimeState.pendingSelectionReference = null;
    }

    function ensureSelectionQuoteButton() {
        if (runtimeState.selectionQuoteButton) {
            return runtimeState.selectionQuoteButton;
        }
        const button = document.createElement("button");
        button.className = "runtime-chat-selection-quote";
        button.type = "button";
        button.textContent = t("runtime.quote_selection");
        button.hidden = true;
        button.addEventListener("click", () => {
            const text = runtimeState.pendingSelectionReference;
            if (text) addChatReference({ type: "selection", text });
            hideSelectionQuoteButton();
        });
        document.body.appendChild(button);
        runtimeState.selectionQuoteButton = button;
        return button;
    }

    function maybeShowSelectionQuoteButton() {
        const selection = window.getSelection ? window.getSelection() : null;
        const text = normalizeReferenceText(
            selection ? selection.toString() : "",
        );
        if (!selection || !text) {
            hideSelectionQuoteButton();
            return;
        }
        const log = get("runtimeChatLog");
        const anchorNode = selection.anchorNode;
        const focusNode = selection.focusNode;
        const anchorElement =
            anchorNode && anchorNode.nodeType === Node.ELEMENT_NODE
                ? anchorNode
                : anchorNode && anchorNode.parentElement;
        const focusElement =
            focusNode && focusNode.nodeType === Node.ELEMENT_NODE
                ? focusNode
                : focusNode && focusNode.parentElement;
        const anchorMessage =
            anchorElement && anchorElement.closest(".runtime-chat-item.bot");
        const focusMessage =
            focusElement && focusElement.closest(".runtime-chat-item.bot");
        if (!log || !anchorMessage || anchorMessage !== focusMessage) {
            hideSelectionQuoteButton();
            return;
        }
        const range = selection.rangeCount ? selection.getRangeAt(0) : null;
        if (!range) {
            hideSelectionQuoteButton();
            return;
        }
        const rect = range.getBoundingClientRect();
        const button = ensureSelectionQuoteButton();
        runtimeState.pendingSelectionReference = text;
        button.textContent = t("runtime.quote_selection");
        button.hidden = false;
        button.style.left = `${Math.max(12, Math.min(rect.left + rect.width / 2, window.innerWidth - 12))}px`;
        button.style.top = `${Math.max(12, rect.top - 38)}px`;
    }

    function renderFileCard(attrs) {
        const fileId = escapeHtml(String(attrs.id || "").trim());
        const name = escapeHtml(String(attrs.name || "file").trim());
        const size = formatFileSize(attrs.size);
        if (!fileId) return `<code>[file]</code>`;
        const href = `/api/runtime/chat/file?id=${encodeURIComponent(fileId)}`;
        return (
            `<div class="runtime-chat-file-card">` +
            `<div class="runtime-chat-file-icon">&#128196;</div>` +
            `<div class="runtime-chat-file-info">` +
            `<div class="runtime-chat-file-name">${name}</div>` +
            (size ? `<div class="runtime-chat-file-size">${size}</div>` : "") +
            `</div>` +
            `<a class="runtime-chat-file-dl" href="${href}" download="${name}">${t("runtime.download") || "Download"}</a>` +
            `</div>`
        );
    }

    function isSafeRenderedUrl(url) {
        const text = String(url || "").trim();
        if (!text) return false;
        try {
            const parsed = new URL(text, window.location.origin);
            return ["http:", "https:", "mailto:"].includes(parsed.protocol);
        } catch (_error) {
            return false;
        }
    }

    function isSafeRenderedImageUrl(url) {
        const text = String(url || "").trim();
        if (!text) return false;
        try {
            const parsed = new URL(text, window.location.origin);
            return ["http:", "https:"].includes(parsed.protocol);
        } catch (_error) {
            return false;
        }
    }

    const SAFE_HTML_TAGS = new Set([
        "a",
        "article",
        "aside",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "del",
        "details",
        "div",
        "em",
        "footer",
        "header",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "kbd",
        "li",
        "main",
        "nav",
        "mark",
        "ol",
        "p",
        "pre",
        "s",
        "section",
        "small",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    ]);
    const DROP_HTML_TAGS = new Set([
        "canvas",
        "embed",
        "form",
        "head",
        "iframe",
        "input",
        "link",
        "math",
        "meta",
        "object",
        "script",
        "style",
        "svg",
        "template",
        "title",
        "video",
    ]);
    const STANDALONE_HTML_ROOT_TAGS = new Set([
        "article",
        "aside",
        "blockquote",
        "body",
        "details",
        "div",
        "footer",
        "header",
        "html",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "ul",
    ]);

    function sanitizeIntegerAttribute(element, name, min, max) {
        const value = Number.parseInt(element.getAttribute(name) || "", 10);
        if (!Number.isFinite(value) || value < min || value > max) {
            element.removeAttribute(name);
            return;
        }
        element.setAttribute(name, String(value));
    }

    function sanitizeHtmlElement(element) {
        const tag = element.tagName.toLowerCase();
        [...element.attributes].forEach((attr) => {
            const name = attr.name.toLowerCase();
            if (name.startsWith("on") || name === "style") {
                element.removeAttribute(attr.name);
                return;
            }
            if (name === "href" && tag === "a") {
                if (!isSafeRenderedUrl(attr.value)) {
                    element.removeAttribute(attr.name);
                    return;
                }
                element.setAttribute("rel", "noreferrer");
                return;
            }
            if (name === "src" && tag === "img") {
                if (!isSafeRenderedImageUrl(attr.value)) {
                    element.remove();
                    return;
                }
                element.classList.add("runtime-chat-image");
                element.setAttribute("loading", "lazy");
                return;
            }
            if (["alt", "title"].includes(name)) return;
            if (
                ["th", "td"].includes(tag) &&
                ["colspan", "rowspan"].includes(name)
            ) {
                sanitizeIntegerAttribute(element, name, 1, 20);
                return;
            }
            if (tag === "ol" && name === "start") {
                sanitizeIntegerAttribute(element, name, 1, 9999);
                return;
            }
            element.removeAttribute(attr.name);
        });
    }

    function sanitizeHtmlNode(node) {
        if (node.nodeType === Node.TEXT_NODE) return;
        if (node.nodeType !== Node.ELEMENT_NODE) {
            node.remove();
            return;
        }
        const element = node;
        const tag = element.tagName.toLowerCase();
        if (DROP_HTML_TAGS.has(tag)) {
            element.remove();
            return;
        }
        if (!SAFE_HTML_TAGS.has(tag)) {
            [...element.childNodes].forEach(sanitizeHtmlNode);
            const parent = element.parentNode;
            if (!parent) {
                element.remove();
                return;
            }
            while (element.firstChild) {
                parent.insertBefore(element.firstChild, element);
            }
            element.remove();
            return;
        }
        sanitizeHtmlElement(element);
        [...element.childNodes].forEach(sanitizeHtmlNode);
    }

    function sanitizeHtmlSnippet(html) {
        const raw = String(html || "");
        if (!raw.trim() || typeof document === "undefined")
            return escapeHtml(raw);
        const template = document.createElement("template");
        template.innerHTML = raw;
        [...template.content.childNodes].forEach(sanitizeHtmlNode);
        return template.innerHTML;
    }

    function looksLikeStandaloneHtml(text) {
        const raw = String(text || "").trim();
        if (!raw || !raw.includes("<") || !raw.includes(">")) return false;
        if (/^```/.test(raw)) return false;
        if (/^<!doctype\s+html\b/i.test(raw)) return true;
        const firstTag = raw.match(/^<([a-z][a-z0-9-]*)\b[^>]*>/i);
        if (!firstTag) return false;
        const tag = firstTag[1].toLowerCase();
        if (tag === "html" || tag === "body") return true;
        if (!STANDALONE_HTML_ROOT_TAGS.has(tag)) return false;
        return new RegExp(`</${tag}>\\s*$`, "i").test(raw);
    }

    const CODE_LANGUAGE_ALIASES = {
        c: "c",
        cc: "cpp",
        cjs: "javascript",
        cs: "csharp",
        htm: "xml",
        html: "xml",
        js: "javascript",
        jsonc: "json",
        jsx: "javascript",
        md: "markdown",
        mjs: "javascript",
        plaintext: "plaintext",
        plain: "plaintext",
        py: "python",
        sh: "bash",
        shell: "bash",
        ts: "typescript",
        tsx: "typescript",
        txt: "plaintext",
        vue: "xml",
        xhtml: "xml",
        yml: "yaml",
    };

    function normalizeCodeLanguage(language) {
        const raw = String(language || "")
            .trim()
            .toLowerCase()
            .replace(/^language-/, "")
            .split(/\s+/)[0]
            .replace(/[^a-z0-9_+#.-]/g, "");
        return CODE_LANGUAGE_ALIASES[raw] || raw || "text";
    }

    function highlightCodeBlock(code, language) {
        const lang = normalizeCodeLanguage(language);
        if (lang === "text" || lang === "plaintext") {
            return escapeHtml(code);
        }
        if (typeof hljs === "undefined") {
            return escapeHtml(code);
        }
        try {
            if (hljs.getLanguage && hljs.getLanguage(lang)) {
                return hljs.highlight(code, {
                    ignoreIllegals: true,
                    language: lang,
                }).value;
            }
            return hljs.highlightAuto(code).value;
        } catch (_e) {
            return escapeHtml(code);
        }
    }

    function isRunnableHtmlCode(code, language) {
        const lang = normalizeCodeLanguage(language);
        if (["html", "xml", "xhtml"].includes(lang)) return true;
        const raw = String(code || "").trim();
        if (!raw) return false;
        return (
            /^<!doctype\s+html\b/i.test(raw) ||
            /^<html\b/i.test(raw) ||
            (/<(style|script)\b/i.test(raw) && /<\/(style|script)>/i.test(raw))
        );
    }

    function codeBlockLanguageLabel(language) {
        const lang = normalizeCodeLanguage(language);
        return lang === "text" ? "code" : lang;
    }

    function shouldCollapseCodeBlock(code) {
        const lines = String(code || "").split(/\r?\n/).length;
        return lines > CODE_COLLAPSE_LINE_THRESHOLD;
    }

    function createSafeMarkedRenderer() {
        if (typeof marked === "undefined" || !marked.Renderer) return null;
        const renderer = new marked.Renderer();
        renderer.html = ({ text }) => sanitizeHtmlSnippet(text || "");
        renderer.code = (token, legacyLanguage) => {
            const codeText =
                token && typeof token === "object"
                    ? String(token.text || "")
                    : String(token || "");
            const language =
                token && typeof token === "object"
                    ? token.lang
                    : legacyLanguage;
            const normalizedLanguage = normalizeCodeLanguage(language);
            const encodedCode = encodeURIComponent(codeText);
            const canRunHtml = isRunnableHtmlCode(codeText, normalizedLanguage);
            const languageClass =
                normalizedLanguage && normalizedLanguage !== "text"
                    ? ` language-${escapeHtml(normalizedLanguage)}`
                    : "";
            const isCollapsible = shouldCollapseCodeBlock(codeText);
            const collapsedClass = isCollapsible ? " is-collapsed" : "";
            return (
                `<div class="runtime-code-block${collapsedClass}" data-language="${escapeHtml(normalizedLanguage)}" data-code="${escapeHtml(encodedCode)}">` +
                `<div class="runtime-code-toolbar">` +
                `<span class="runtime-code-language">${escapeHtml(codeBlockLanguageLabel(normalizedLanguage))}</span>` +
                `<span class="runtime-code-actions">` +
                (isCollapsible
                    ? `<button class="runtime-code-action" type="button" data-code-toggle data-collapsed-label="${escapeHtml(t("runtime.expand_code"))}" data-expanded-label="${escapeHtml(t("runtime.collapse_code"))}">${escapeHtml(t("runtime.expand_code"))}</button>`
                    : "") +
                `<button class="runtime-code-action" type="button" data-code-copy>${escapeHtml(t("runtime.copy_code"))}</button>` +
                (canRunHtml
                    ? `<button class="runtime-code-action primary" type="button" data-code-run-html>${escapeHtml(t("runtime.run_html"))}</button>`
                    : "") +
                `</span>` +
                `</div>` +
                `<pre class="runtime-code-body">` +
                `<code class="${languageClass.trim()}">` +
                `${highlightCodeBlock(codeText, normalizedLanguage)}` +
                `</code></pre>` +
                `</div>`
            );
        };
        renderer.blockquote = ({ tokens }) => {
            const parser = renderer.parser || marked.Parser;
            const body =
                parser && typeof parser.parse === "function"
                    ? parser.parse(tokens || [])
                    : "";
            return (
                `<details class="runtime-quote-block">` +
                `<summary><span>${escapeHtml(t("runtime.quote"))}</span></summary>` +
                `<div class="runtime-quote-body">${body}</div>` +
                `</details>`
            );
        };
        renderer.link = ({ href, title, tokens }) => {
            const parser = renderer.parser || marked.Parser;
            const label =
                parser && typeof parser.parseInline === "function"
                    ? parser.parseInline(tokens || [])
                    : escapeHtml(href || "");
            if (!isSafeRenderedUrl(href)) return label;
            const rawHref = String(href || "").trim();
            const parsed = new URL(rawHref, window.location.origin);
            const safeHref = escapeHtml(
                parsed.origin === window.location.origin &&
                    !rawHref.match(/^[a-z][a-z0-9+.-]*:/i)
                    ? `${parsed.pathname}${parsed.search}${parsed.hash}`
                    : parsed.toString(),
            );
            const safeTitle = title
                ? ` title="${escapeHtml(String(title))}"`
                : "";
            return (
                `<a href="${safeHref}"${safeTitle} rel="noreferrer">` +
                `${label}</a>`
            );
        };
        renderer.image = ({ text }) => escapeHtml(text || "");
        return renderer;
    }

    function renderChatContent(content, useMarkdown) {
        const text = String(content || "");

        // Extract CQ file codes into placeholders
        const filePattern = /\[CQ:file,([^\]]+)\]/g;
        const filePlaceholders = [];
        const step1 = text.replace(filePattern, (match, attrStr) => {
            const attrs = parseCqAttributes(attrStr);
            const idx = filePlaceholders.length;
            filePlaceholders.push(renderFileCard(attrs));
            return `CQFILEPH${idx}CQFILEPH`;
        });

        // Extract CQ image codes into placeholders before markdown parsing
        const imagePattern = /\[CQ:image,([^\]]+)\]/g;
        const images = [];
        const processed = step1.replace(imagePattern, (match, attrStr) => {
            const attrs = parseCqAttributes(attrStr);
            const src = resolveCqImageSource(attrs);
            if (src) {
                const idx = images.length;
                images.push(
                    `<img class="runtime-chat-image" src="${escapeHtml(src)}" alt="image" loading="lazy" />`,
                );
                return `CQIMGPH${idx}CQIMGPH`;
            }
            return match;
        });

        let html;
        if (useMarkdown && looksLikeStandaloneHtml(processed)) {
            html = sanitizeHtmlSnippet(processed);
        } else if (
            useMarkdown &&
            typeof marked !== "undefined" &&
            marked.parse
        ) {
            try {
                html = marked.parse(processed, {
                    breaks: true,
                    gfm: true,
                    renderer: createSafeMarkedRenderer(),
                });
            } catch (_e) {
                html = escapeHtml(processed);
            }
        } else {
            html = escapeHtml(processed);
        }

        // Restore placeholders
        for (let i = 0; i < images.length; i++) {
            html = html.replace(
                new RegExp(`CQIMGPH${i}CQIMGPH`, "g"),
                images[i],
            );
        }
        for (let i = 0; i < filePlaceholders.length; i++) {
            // marked may wrap placeholder in <p>, strip it for block-level card
            html = html.replace(
                new RegExp(`<p>\\s*CQFILEPH${i}CQFILEPH\\s*</p>`, "g"),
                filePlaceholders[i],
            );
            html = html.replace(
                new RegExp(`CQFILEPH${i}CQFILEPH`, "g"),
                filePlaceholders[i],
            );
        }

        return html || escapeHtml(text);
    }

    function decodeCodeBlockPayload(block) {
        const encoded = String((block && block.dataset.code) || "");
        if (!encoded) return "";
        try {
            return decodeURIComponent(encoded);
        } catch (_error) {
            return "";
        }
    }

    async function copyTextToClipboard(text) {
        const value = String(text || "");
        if (!value) return false;
        if (
            navigator.clipboard &&
            typeof navigator.clipboard.writeText === "function"
        ) {
            try {
                await navigator.clipboard.writeText(value);
                return true;
            } catch (_error) {
                // fall through to textarea fallback
            }
        }
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.top = "-1000px";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        let ok = false;
        try {
            ok = document.execCommand("copy");
        } catch (_error) {
            ok = false;
        } finally {
            textarea.remove();
        }
        return ok;
    }

    async function copyCodeBlock(block) {
        const text = decodeCodeBlockPayload(block);
        const ok = await copyTextToClipboard(text);
        showToast(
            ok ? t("runtime.code_copied") : t("runtime.copy_failed"),
            ok ? "success" : "error",
            1800,
        );
    }

    function runHtmlCodeBlock(block) {
        const code = decodeCodeBlockPayload(block);
        if (!code) return;
        if (typeof openHtmlRunner === "function") {
            openHtmlRunner(code, {
                language: String((block && block.dataset.language) || "html"),
            });
            return;
        }
        showToast(t("runtime.run_html"), "info", 1200);
    }

    function toggleCodeBlock(block) {
        if (!block) return;
        const nextCollapsed = !block.classList.contains("is-collapsed");
        block.classList.toggle("is-collapsed", nextCollapsed);
        const button = block.querySelector("[data-code-toggle]");
        if (button) {
            button.textContent = nextCollapsed
                ? button.getAttribute("data-collapsed-label") ||
                  t("runtime.expand_code")
                : button.getAttribute("data-expanded-label") ||
                  t("runtime.collapse_code");
            button.setAttribute(
                "aria-expanded",
                nextCollapsed ? "false" : "true",
            );
        }
    }

    function buildHtmlRunnerDocument(source) {
        const raw = String(source || "").trim();
        if (!raw) return "";
        if (/^<!doctype\s+html\b/i.test(raw) || /^<html\b/i.test(raw)) {
            return raw;
        }
        return (
            `<!doctype html><html><head><meta charset="utf-8">` +
            `<meta name="viewport" content="width=device-width, initial-scale=1">` +
            `</head><body>${raw}</body></html>`
        );
    }

    function htmlRunnerPickerScript() {
        const confirmHint = JSON.stringify(t("runtime.html_pick_confirm_hint"));
        return `<script>
(() => {
  let active = false;
  let selected = null;
  let locked = null;
  let rafId = 0;
  const confirmHint = ${confirmHint};
  const overlay = document.createElement("div");
  const label = document.createElement("div");
  const style = document.createElement("style");
  style.textContent = [
    "html[data-webui-html-picking],html[data-webui-html-picking] *{cursor:crosshair!important;}",
    "[data-webui-html-picker-overlay]{position:fixed;z-index:2147483646;pointer-events:none;border:2px solid #d97757;background:rgba(217,119,87,.12);box-shadow:0 0 0 99999px rgba(15,23,42,.08);border-radius:2px;display:none;}",
    "[data-webui-html-picker-label]{position:fixed;z-index:2147483647;pointer-events:none;max-width:min(360px,calc(100vw - 16px));padding:3px 6px;border-radius:4px;background:#d97757;color:#fff;font:11px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:none;box-shadow:0 6px 18px rgba(15,23,42,.22);}",
  ].join("");
  overlay.setAttribute("data-webui-html-picker-overlay", "1");
  label.setAttribute("data-webui-html-picker-label", "1");
  document.documentElement.appendChild(style);
  function mount() {
    if (!document.body) return;
    if (!overlay.parentNode) document.body.appendChild(overlay);
    if (!label.parentNode) document.body.appendChild(label);
  }
  function elementLabel(element) {
    if (!element || !element.tagName) return "";
    let text = element.tagName.toLowerCase();
    if (element.id) text += "#" + element.id;
    if (element.classList && element.classList.length) {
      text += "." + Array.from(element.classList).slice(0, 3).join(".");
    }
    const rect = element.getBoundingClientRect();
    text += " " + Math.round(rect.width) + "×" + Math.round(rect.height);
    return text;
  }
  function clear() {
    selected = null;
    locked = null;
    overlay.style.display = "none";
    label.style.display = "none";
  }
  function candidateFromPoint(x, y) {
    const elements = document.elementsFromPoint
      ? document.elementsFromPoint(x, y)
      : [document.elementFromPoint(x, y)];
    return (elements || []).find((element) => {
      if (!element || element === overlay || element === label) return false;
      if (element === document.documentElement || element === document.body) return false;
      return element.nodeType === Node.ELEMENT_NODE;
    }) || document.body || document.documentElement;
  }
  function draw(element) {
    mount();
    if (!element) {
      clear();
      return;
    }
    const rect = element.getBoundingClientRect();
    if (!rect.width && !rect.height) {
      clear();
      return;
    }
    selected = element;
    overlay.style.display = "block";
    overlay.style.left = Math.max(0, rect.left) + "px";
    overlay.style.top = Math.max(0, rect.top) + "px";
    overlay.style.width = Math.max(0, rect.width) + "px";
    overlay.style.height = Math.max(0, rect.height) + "px";
    const labelText = elementLabel(element);
    const suffix = locked === element && confirmHint ? " · " + confirmHint : "";
    label.textContent = labelText + suffix;
    label.style.display = labelText ? "block" : "none";
    const labelTop = rect.top >= 24 ? rect.top - 24 : rect.bottom + 4;
    label.style.left = Math.min(Math.max(8, rect.left), window.innerWidth - 16) + "px";
    label.style.top = Math.min(Math.max(8, labelTop), window.innerHeight - 24) + "px";
  }
  function scheduleDraw(element) {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      draw(element);
    });
  }
  function setActive(nextActive) {
    active = !!nextActive;
    document.documentElement.toggleAttribute("data-webui-html-picking", active);
    if (!active) clear();
    else mount();
  }
  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "webui-html-pick") return;
    setActive(event.data.active);
  });
  document.addEventListener("mousemove", (event) => {
    if (!active) return;
    if (locked) return;
    scheduleDraw(candidateFromPoint(event.clientX, event.clientY));
  }, true);
  document.addEventListener("pointerdown", (event) => {
    if (!active) return;
    event.preventDefault();
    event.stopPropagation();
    if (!locked) {
      locked = selected || candidateFromPoint(event.clientX, event.clientY);
      scheduleDraw(locked);
      return;
    }
    const target = locked;
    const html = target && target.outerHTML ? target.outerHTML : "";
    parent.postMessage({ type: "webui-html-picked", html }, "*");
    setActive(false);
  }, true);
  window.addEventListener("load", () => {
    parent.postMessage({ type: "webui-html-picker-ready" }, "*");
  });
  parent.postMessage({ type: "webui-html-picker-ready" }, "*");
  document.addEventListener("mouseleave", () => {
    if (active && !locked) clear();
  }, true);
  window.addEventListener("scroll", () => {
    if (active && selected) scheduleDraw(selected);
  }, true);
  window.addEventListener("resize", () => {
    if (active && selected) scheduleDraw(selected);
  });
})();
<\/script>`;
    }

    function injectHtmlRunnerPicker(html) {
        const script = htmlRunnerPickerScript();
        if (/<\/body>/i.test(html)) {
            return html.replace(/<\/body>/i, `${script}</body>`);
        }
        return `${html}${script}`;
    }

    function syncHtmlRunnerPickModeToFrame() {
        const frame = get("runtimeHtmlRunnerFrame");
        if (frame && frame.contentWindow) {
            frame.contentWindow.postMessage(
                {
                    type: "webui-html-pick",
                    active: !!runtimeState.htmlRunnerPickMode,
                },
                "*",
            );
        }
    }

    function setHtmlRunnerPickMode(active) {
        runtimeState.htmlRunnerPickMode = !!active;
        const runner = get("runtimeHtmlRunner");
        const button = get("btnRuntimeHtmlPick");
        if (runner) runner.classList.toggle("is-picking", !!active);
        if (button) {
            button.textContent = active
                ? t("runtime.picking_html")
                : t("runtime.pick_html");
            button.classList.toggle("is-active", !!active);
            button.setAttribute("aria-pressed", active ? "true" : "false");
        }
        syncHtmlRunnerPickModeToFrame();
        if (active) showToast(t("runtime.html_pick_hint"), "info", 1800);
    }

    function clampHtmlRunnerSize(width, height) {
        const viewportWidth = Math.max(
            0,
            window.innerWidth - HTML_RUNNER_VIEWPORT_MARGIN * 2,
        );
        const viewportHeight = Math.max(
            0,
            window.innerHeight - HTML_RUNNER_VIEWPORT_MARGIN * 2,
        );
        const minWidth = Math.min(HTML_RUNNER_MIN_WIDTH, viewportWidth);
        const minHeight = Math.min(HTML_RUNNER_MIN_HEIGHT, viewportHeight);
        const maxWidth = Math.max(minWidth, viewportWidth);
        const maxHeight = Math.max(minHeight, viewportHeight);
        return {
            width: Math.min(Math.max(width, minWidth), maxWidth),
            height: Math.min(Math.max(height, minHeight), maxHeight),
        };
    }

    function clampHtmlRunnerPosition(left, top, width, height) {
        const maxLeft = Math.max(
            HTML_RUNNER_VIEWPORT_MARGIN,
            window.innerWidth - width - HTML_RUNNER_VIEWPORT_MARGIN,
        );
        const maxTop = Math.max(
            HTML_RUNNER_VIEWPORT_MARGIN,
            window.innerHeight - height - HTML_RUNNER_VIEWPORT_MARGIN,
        );
        return {
            left: Math.min(
                Math.max(Number(left), HTML_RUNNER_VIEWPORT_MARGIN),
                maxLeft,
            ),
            top: Math.min(
                Math.max(Number(top), HTML_RUNNER_VIEWPORT_MARGIN),
                maxTop,
            ),
        };
    }

    function setHtmlRunnerRect(left, top, width, height) {
        const runner = get("runtimeHtmlRunner");
        if (!runner) return;
        const size = clampHtmlRunnerSize(Number(width), Number(height));
        const position = clampHtmlRunnerPosition(
            Number(left),
            Number(top),
            size.width,
            size.height,
        );
        runner.style.left = `${position.left}px`;
        runner.style.top = `${position.top}px`;
        runner.style.width = `${size.width}px`;
        runner.style.height = `${size.height}px`;
    }

    function setHtmlRunnerSize(width, height) {
        const runner = get("runtimeHtmlRunner");
        if (!runner) return;
        const rect = runner.getBoundingClientRect();
        setHtmlRunnerRect(rect.left, rect.top, width, height);
    }

    function clearHtmlRunnerInteraction(pointerId = null) {
        const runner = get("runtimeHtmlRunner");
        const resize = runtimeState.htmlRunnerResize;
        const drag = runtimeState.htmlRunnerDrag;
        if (pointerId === null || (resize && resize.pointerId === pointerId)) {
            runtimeState.htmlRunnerResize = null;
            if (runner) runner.classList.remove("is-resizing");
        }
        if (pointerId === null || (drag && drag.pointerId === pointerId)) {
            runtimeState.htmlRunnerDrag = null;
            if (runner) runner.classList.remove("is-dragging");
        }
    }

    function ensureHtmlRunnerInitialRect(runner) {
        if (!runner || (runner.style.left && runner.style.top)) return;
        const initialWidth = Math.min(
            760,
            window.innerWidth - HTML_RUNNER_VIEWPORT_MARGIN * 2,
        );
        const initialHeight = Math.min(
            360,
            window.innerHeight - HTML_RUNNER_VIEWPORT_MARGIN * 2,
        );
        setHtmlRunnerRect(
            window.innerWidth - initialWidth - 32,
            window.innerHeight - initialHeight - 32,
            initialWidth,
            initialHeight,
        );
    }

    function openHtmlRunner(source, options = {}) {
        const runner = get("runtimeHtmlRunner");
        const frame = get("runtimeHtmlRunnerFrame");
        const meta = get("runtimeHtmlRunnerMeta");
        if (!runner || !frame) return;
        const html = buildHtmlRunnerDocument(source);
        if (!html) return;
        runtimeState.htmlRunnerSource = String(source || "");
        runtimeState.htmlRunnerPickMode = false;
        runner.hidden = false;
        runner.classList.remove("is-picking");
        clearHtmlRunnerInteraction();
        ensureHtmlRunnerInitialRect(runner);
        const button = get("btnRuntimeHtmlPick");
        if (button) {
            button.textContent = t("runtime.pick_html");
            button.classList.remove("is-active");
            button.setAttribute("aria-pressed", "false");
        }
        if (meta) {
            meta.textContent = String(options.language || "html").toUpperCase();
        }
        frame.srcdoc = injectHtmlRunnerPicker(html);
        showToast(t("runtime.html_ready"), "success", 1200);
    }

    function closeHtmlRunner() {
        const runner = get("runtimeHtmlRunner");
        const frame = get("runtimeHtmlRunnerFrame");
        clearHtmlRunnerInteraction();
        if (runner) runner.hidden = true;
        if (frame) frame.srcdoc = "";
        runtimeState.htmlRunnerSource = "";
        runtimeState.htmlRunnerPickMode = false;
        const button = get("btnRuntimeHtmlPick");
        if (button) {
            button.textContent = t("runtime.pick_html");
            button.classList.remove("is-active");
            button.setAttribute("aria-pressed", "false");
        }
    }

    function handleHtmlRunnerPicked(html) {
        const picked = String(html || "").trim();
        if (!picked) return;
        setHtmlRunnerPickMode(false);
        addChatReference({ type: "html", text: picked });
    }

    function startHtmlRunnerResize(event) {
        const runner = get("runtimeHtmlRunner");
        if (!runner) return;
        event.preventDefault();
        event.stopPropagation();
        const pointerId = event.pointerId;
        const rect = runner.getBoundingClientRect();
        runtimeState.htmlRunnerResize = {
            pointerId,
            startX: event.clientX,
            startY: event.clientY,
            startWidth: rect.width,
            startHeight: rect.height,
        };
        runner.classList.add("is-resizing");
        const handle = event.currentTarget;
        if (handle && typeof handle.setPointerCapture === "function") {
            handle.setPointerCapture(pointerId);
        }
    }

    function moveHtmlRunnerResize(event) {
        const state = runtimeState.htmlRunnerResize;
        if (!state || state.pointerId !== event.pointerId) return;
        event.preventDefault();
        setHtmlRunnerSize(
            state.startWidth + event.clientX - state.startX,
            state.startHeight + event.clientY - state.startY,
        );
    }

    function stopHtmlRunnerResize(event) {
        const state = runtimeState.htmlRunnerResize;
        if (!state || state.pointerId !== event.pointerId) return;
        const handle = event.currentTarget;
        if (handle && typeof handle.releasePointerCapture === "function") {
            handle.releasePointerCapture(state.pointerId);
        }
        clearHtmlRunnerInteraction(state.pointerId);
    }

    function startHtmlRunnerDrag(event) {
        const target = event.target;
        if (target instanceof Element && target.closest("button")) return;
        const runner = get("runtimeHtmlRunner");
        if (!runner) return;
        event.preventDefault();
        const pointerId = event.pointerId;
        const rect = runner.getBoundingClientRect();
        runtimeState.htmlRunnerDrag = {
            pointerId,
            startX: event.clientX,
            startY: event.clientY,
            startLeft: rect.left,
            startTop: rect.top,
            startWidth: rect.width,
            startHeight: rect.height,
        };
        runner.classList.add("is-dragging");
        const handle = event.currentTarget;
        if (handle && typeof handle.setPointerCapture === "function") {
            handle.setPointerCapture(pointerId);
        }
    }

    function moveHtmlRunnerDrag(event) {
        const state = runtimeState.htmlRunnerDrag;
        if (!state || state.pointerId !== event.pointerId) return;
        event.preventDefault();
        setHtmlRunnerRect(
            state.startLeft + event.clientX - state.startX,
            state.startTop + event.clientY - state.startY,
            state.startWidth,
            state.startHeight,
        );
    }

    function stopHtmlRunnerDrag(event) {
        const state = runtimeState.htmlRunnerDrag;
        if (!state || state.pointerId !== event.pointerId) return;
        const handle = event.currentTarget;
        if (handle && typeof handle.releasePointerCapture === "function") {
            handle.releasePointerCapture(state.pointerId);
        }
        clearHtmlRunnerInteraction(state.pointerId);
    }

    function clampVisibleHtmlRunner() {
        const runner = get("runtimeHtmlRunner");
        if (!runner || runner.hidden) return;
        const rect = runner.getBoundingClientRect();
        setHtmlRunnerRect(rect.left, rect.top, rect.width, rect.height);
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

    async function uploadChatFile(file) {
        const form = new FormData();
        form.append("file", file, formatAttachmentName(file));
        const res = await api("/api/runtime/chat/files", {
            method: "POST",
            body: form,
        });
        const data = await parseJsonSafe(res);
        if (!res.ok || (data && data.error)) {
            throw new Error(buildRequestError(res, data));
        }
        if (!data || !data.id) {
            throw new Error("missing file id");
        }
        return data;
    }

    async function attachmentToMessageSegment(item) {
        const file = item && item.file;
        if (!file) return "";
        if (
            item.kind === "image" &&
            Number(file.size || 0) <= CHAT_INLINE_IMAGE_MAX_BYTES
        ) {
            const dataUrl = await readFileAsDataUrl(file);
            const base64 = String(dataUrl).split(",", 2)[1] || "";
            if (!base64) return "";
            return `[CQ:image,file=base64://${base64}]`;
        }
        const uploaded = await uploadChatFile(file);
        const id = String(uploaded.id || "");
        const name = String(uploaded.name || item.name || "file");
        const size = Number(uploaded.size || item.size || 0);
        return `[CQ:file,id=${id},name=${name},size=${size}]`;
    }

    async function buildChatMessageWithAttachments(
        message,
        attachments,
        references = runtimeState.chatReferences,
    ) {
        const quotedMessage = buildChatMessageWithReferences(
            message,
            references,
        );
        const parts = [quotedMessage].filter(Boolean);
        for (const item of attachments || []) {
            const segment = await attachmentToMessageSegment(item);
            if (segment) parts.push(segment);
        }
        return parts.join("\n").trim();
    }

    async function fetchJsonOrThrow(path, options = {}) {
        const res = await api(path, options);
        const data = await parseJsonSafe(res);
        if (!res.ok || (data && data.error)) {
            throw new Error(buildRequestError(res, data));
        }
        return data || {};
    }

    function buildRequestError(res, payload) {
        const fallback =
            `${res.status} ${res.statusText || "Request failed"}`.trim();
        if (!payload || typeof payload !== "object") return fallback;
        const base = payload.error ? String(payload.error) : fallback;
        return payload.detail ? `${base}: ${payload.detail}` : base;
    }

    function appendRuntimeApiHint(message) {
        const text = String(message || "").trim();
        if (!text) return text;
        const normalized = text.toLowerCase();
        const unreachable =
            normalized.includes("runtime api unreachable") ||
            normalized.includes("failed to fetch") ||
            normalized.includes("networkerror") ||
            normalized.includes(" 502 ") ||
            normalized.startsWith("502 ");
        if (!unreachable) return text;
        const hint = t("runtime.api_start_hint");
        if (!hint || text.includes(hint)) return text;
        return `${text} ${hint}`;
    }

    let _memoryMutating = false;

    function renderMemoryItems(payload) {
        const container = get("runtimeMemoryList");
        const meta = get("runtimeMemoryMeta");
        if (!container || !meta) return;
        const items =
            payload && Array.isArray(payload.items) ? payload.items : [];
        const queryInfo =
            payload && payload.query && typeof payload.query === "object"
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
                return `<div class="runtime-list-item" data-uuid="${uuid}"><div class="runtime-list-head"><code>${uuid}</code><div class="memory-item-actions"><button class="memory-btn-edit" title="编辑" data-uuid="${uuid}">✏️</button><button class="memory-btn-delete" title="删除" data-uuid="${uuid}">🗑️</button></div></div><div class="runtime-list-head" style="margin-bottom:0"><span>${created}</span></div><div class="runtime-list-fact">${fact}</div></div>`;
            })
            .join("");

        container.querySelectorAll(".memory-btn-edit").forEach((btn) => {
            btn.addEventListener("click", () =>
                startEditMemory(btn.dataset.uuid),
            );
        });
        container.querySelectorAll(".memory-btn-delete").forEach((btn) => {
            btn.addEventListener("click", () => deleteMemory(btn.dataset.uuid));
        });
    }

    function startEditMemory(uuid) {
        const container = get("runtimeMemoryList");
        if (!container) return;
        const itemEl = container.querySelector(
            `.runtime-list-item[data-uuid="${CSS.escape(uuid)}"]`,
        );
        if (!itemEl) return;
        const factEl = itemEl.querySelector(".runtime-list-fact");
        if (!factEl || factEl.dataset.editing === "true") return;

        const currentText = factEl.textContent || "";
        factEl.dataset.editing = "true";
        factEl.innerHTML = "";

        const textarea = document.createElement("textarea");
        textarea.className = "form-control memory-edit-area";
        textarea.value = currentText;

        const actions = document.createElement("div");
        actions.className = "memory-edit-actions";
        const saveBtn = document.createElement("button");
        saveBtn.className = "btn btn-sm";
        saveBtn.textContent = "保存";
        const cancelBtn = document.createElement("button");
        cancelBtn.className = "btn btn-sm";
        cancelBtn.textContent = "取消";
        actions.append(saveBtn, cancelBtn);
        factEl.append(textarea, actions);
        textarea.focus();

        cancelBtn.addEventListener("click", () => {
            delete factEl.dataset.editing;
            factEl.innerHTML = "";
            factEl.textContent = currentText;
        });

        saveBtn.addEventListener("click", () =>
            updateMemory(uuid, textarea.value),
        );

        textarea.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                e.preventDefault();
                cancelBtn.click();
            }
            if (e.key === "Enter" && e.ctrlKey) {
                e.preventDefault();
                saveBtn.click();
            }
        });
    }

    async function createMemory() {
        if (_memoryMutating) return;
        const input = get("memoryCreateInput");
        if (!input) return;
        const fact = String(input.value || "").trim();
        if (!fact) {
            showToast("记忆内容不能为空", "warning");
            return;
        }
        _memoryMutating = true;
        const btn = get("btnMemoryCreate");
        if (btn) btn.disabled = true;
        try {
            const res = await api("/api/runtime/memory", {
                method: "POST",
                body: JSON.stringify({ fact }),
            });
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            showToast("记忆已添加", "success");
            input.value = "";
            await searchMemory();
        } catch (err) {
            showToast(`添加失败: ${err.message || err}`, "error");
        } finally {
            _memoryMutating = false;
            if (btn) btn.disabled = false;
        }
    }

    async function updateMemory(uuid, newFact) {
        const fact = String(newFact || "").trim();
        if (!fact) {
            showToast("记忆内容不能为空", "warning");
            return;
        }
        if (_memoryMutating) return;
        _memoryMutating = true;
        try {
            const res = await api(
                `/api/runtime/memory/${encodeURIComponent(uuid)}`,
                {
                    method: "PATCH",
                    body: JSON.stringify({ fact }),
                },
            );
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            showToast("记忆已更新", "success");
            await searchMemory();
        } catch (err) {
            showToast(`更新失败: ${err.message || err}`, "error");
        } finally {
            _memoryMutating = false;
        }
    }

    async function deleteMemory(uuid) {
        if (_memoryMutating) return;
        if (!confirm(`确认删除记忆 ${uuid.slice(0, 8)}…？`)) return;
        _memoryMutating = true;
        try {
            const res = await api(
                `/api/runtime/memory/${encodeURIComponent(uuid)}`,
                {
                    method: "DELETE",
                },
            );
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            showToast("记忆已删除", "success");
            await searchMemory();
        } catch (err) {
            showToast(`删除失败: ${err.message || err}`, "error");
        } finally {
            _memoryMutating = false;
        }
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
        const items =
            payload && Array.isArray(payload.items) ? payload.items : [];
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

        list.innerHTML = items
            .map((item, index) => {
                const doc = escapeHtml(
                    String((item && item.document) || "").trim(),
                );
                const md =
                    item && typeof item.metadata === "object" && item.metadata
                        ? item.metadata
                        : {};
                const dist = formatNumeric(item && item.distance);
                const rerank = formatNumeric(item && item.rerank_score);
                const timestamp = escapeHtml(
                    String(md.timestamp_local || "").trim(),
                );
                const headLabel = timestamp || `#${index + 1}`;
                const tags = [];
                if (dist)
                    tags.push(
                        `<span class="runtime-tag">distance ${dist}</span>`,
                    );
                if (rerank)
                    tags.push(
                        `<span class="runtime-tag">rerank ${rerank}</span>`,
                    );

                const metaRows = preferredMetaKeys
                    .filter(
                        (key) =>
                            md[key] !== undefined &&
                            md[key] !== null &&
                            String(md[key]).trim() !== "",
                    )
                    .map((key) => {
                        const raw = md[key];
                        const text =
                            raw && typeof raw === "object"
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
            })
            .join("");
    }

    function renderProfileDetail(payload) {
        const meta = get("runtimeProfileMeta");
        const container = get("runtimeProfileResult");
        if (!meta || !container) return;
        if (!payload || typeof payload !== "object") {
            setListMessage(
                "runtimeProfileMeta",
                "runtimeProfileResult",
                t("runtime.empty"),
            );
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
        renderInternalProbe({ error: msg });
        renderExternalProbe({ error: msg });
    }

    function setMemoryUnavailable(message) {
        const msg = String(message || RUNTIME_DISABLED_ERROR);
        setListMessage("runtimeMemoryMeta", "runtimeMemoryList", msg);
        setListMessage("runtimeEventsMeta", "runtimeEventsResult", msg);
        setListMessage("runtimeProfilesMeta", "runtimeProfilesResult", msg);
        setListMessage("runtimeProfileMeta", "runtimeProfileResult", msg);
    }

    async function fetchRuntimeMeta() {
        return fetchJsonOrThrow([
            "/api/v1/management/runtime/meta",
            "/api/runtime/meta",
        ]);
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
        const data = await fetchJsonOrThrow([
            "/api/v1/management/runtime/probes/internal",
            "/api/runtime/probes/internal",
        ]);
        renderInternalProbe(data);
    }

    async function fetchExternalProbe() {
        const data = await fetchJsonOrThrow([
            "/api/v1/management/runtime/probes/external",
            "/api/runtime/probes/external",
        ]);
        renderExternalProbe(data);
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
        const data = await fetchJsonOrThrow(
            `/api/runtime/memory?${params.toString()}`,
        );
        renderMemoryItems(data);
    }

    async function searchEvents() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage(
                "runtimeEventsMeta",
                "runtimeEventsResult",
                t("runtime.disabled"),
            );
            return;
        }
        const query = readInputValue("runtimeEventsQuery");
        if (!query) {
            setListMessage(
                "runtimeEventsMeta",
                "runtimeEventsResult",
                "q is required",
            );
            return;
        }
        const params = new URLSearchParams();
        appendQueryParam(params, "q", query);
        appendPositiveIntParam(
            params,
            "top_k",
            readInputValue("runtimeEventsTopK"),
        );
        appendQueryParam(
            params,
            "request_type",
            readInputValue("runtimeEventsRequestType"),
        );
        appendQueryParam(
            params,
            "target_user_id",
            readInputValue("runtimeEventsTargetUserId"),
        );
        appendQueryParam(
            params,
            "target_group_id",
            readInputValue("runtimeEventsTargetGroupId"),
        );
        appendQueryParam(
            params,
            "sender_id",
            readInputValue("runtimeEventsSenderId"),
        );
        appendQueryParam(
            params,
            "time_from",
            readInputValue("runtimeEventsTimeFrom"),
        );
        appendQueryParam(
            params,
            "time_to",
            readInputValue("runtimeEventsTimeTo"),
        );
        const data = await fetchJsonOrThrow(
            `/api/runtime/cognitive/events?${params.toString()}`,
        );
        renderCognitiveItems("runtimeEventsMeta", "runtimeEventsResult", data);
    }

    async function searchProfiles() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage(
                "runtimeProfilesMeta",
                "runtimeProfilesResult",
                t("runtime.disabled"),
            );
            return;
        }
        const query = readInputValue("runtimeProfilesQuery");
        if (!query) {
            setListMessage(
                "runtimeProfilesMeta",
                "runtimeProfilesResult",
                "q is required",
            );
            return;
        }
        const params = new URLSearchParams();
        appendQueryParam(params, "q", query);
        appendPositiveIntParam(
            params,
            "top_k",
            readInputValue("runtimeProfilesTopK"),
        );
        appendQueryParam(
            params,
            "entity_type",
            readInputValue("runtimeProfilesEntityType"),
        );
        const data = await fetchJsonOrThrow(
            `/api/runtime/cognitive/profiles?${params.toString()}`,
        );
        renderCognitiveItems(
            "runtimeProfilesMeta",
            "runtimeProfilesResult",
            data,
        );
    }

    async function fetchProfileByEntity() {
        if (!(await ensureRuntimeEnabled())) {
            setListMessage(
                "runtimeProfileMeta",
                "runtimeProfileResult",
                t("runtime.disabled"),
            );
            return;
        }
        const entityType = readInputValue("runtimeProfileEntityType");
        const entityId = readInputValue("runtimeProfileEntityId");
        if (!entityType || !entityId) {
            setListMessage(
                "runtimeProfileMeta",
                "runtimeProfileResult",
                "entity_type/entity_id are required",
            );
            return;
        }
        const data = await fetchJsonOrThrow(
            `/api/runtime/cognitive/profile/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`,
        );
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
                5000,
            );
        } finally {
            setButtonLoading(button, false);
            runtimeState.queryBusy[kind] = false;
        }
    }

    function chatConversationTitle(item) {
        return (
            String(item && item.title ? item.title : "").trim() ||
            t("runtime.chat_new_conversation")
        );
    }

    function updateCurrentConversationTitle() {
        const titleEl = get("runtimeChatCurrentTitle");
        const metaEl = get("runtimeChatCurrentMeta");
        const conversation = runtimeState.chatConversations.find(
            (item) => String(item.id) === currentChatConversationId(),
        );
        if (titleEl) {
            titleEl.textContent = conversation
                ? chatConversationTitle(conversation)
                : t("runtime.chat_new_conversation");
        }
        if (metaEl) {
            const count = conversation
                ? Number(conversation.message_count || 0)
                : 0;
            const status = conversation
                ? String(conversation.title_status || "")
                : "";
            const parts = [
                i18nFormat("runtime.chat_message_count", { count }),
                status === "pending" || status === "failed"
                    ? t("runtime.chat_title_pending")
                    : "",
            ].filter(Boolean);
            metaEl.textContent = parts.join(" · ");
        }
    }

    function renderChatConversationList() {
        const list = get("runtimeChatConversations");
        if (!list) return;
        const conversations = Array.isArray(runtimeState.chatConversations)
            ? runtimeState.chatConversations
            : [];
        if (!conversations.length) {
            list.innerHTML = `<div class="runtime-chat-conversation-empty">${escapeHtml(t("runtime.chat_no_conversations"))}</div>`;
            updateCurrentConversationTitle();
            return;
        }
        const activeId = currentChatConversationId();
        list.innerHTML = conversations
            .map((item) => {
                const id = String(item.id || "");
                const active = id && id === activeId;
                const running = !!item.is_running;
                const newlyCreated =
                    id && id === runtimeState.recentlyCreatedConversationId;
                const title = chatConversationTitle(item);
                const updated = String(item.updated_at || "").replace("T", " ");
                return (
                    `<div class="runtime-chat-conversation${active ? " active" : ""}${running ? " running" : ""}${newlyCreated ? " is-new" : ""}" data-conversation-id="${escapeHtml(id)}">` +
                    `<button class="runtime-chat-conversation-main" type="button" data-conversation-select="${escapeHtml(id)}">` +
                    `<span class="runtime-chat-conversation-title">${escapeHtml(title)}</span>` +
                    `<span class="runtime-chat-conversation-meta">${escapeHtml(running ? t("runtime.running") : updated)}</span>` +
                    `</button>` +
                    `<button class="runtime-chat-conversation-rename" type="button" data-conversation-rename="${escapeHtml(id)}" aria-label="${escapeHtml(t("runtime.chat_rename_conversation"))}">✎</button>` +
                    `<button class="runtime-chat-conversation-delete" type="button" data-conversation-delete="${escapeHtml(id)}" aria-label="${escapeHtml(t("runtime.chat_delete_conversation"))}">×</button>` +
                    `</div>`
                );
            })
            .join("");
        updateCurrentConversationTitle();
    }

    function setChatConversationDrawerOpen(open) {
        runtimeState.chatConversationDrawerOpen = !!open;
        const drawer = document.querySelector(".runtime-chat-sidebar");
        const toggle = get("runtimeChatConversationDrawerToggle");
        if (drawer) {
            drawer.classList.toggle(
                "is-open",
                runtimeState.chatConversationDrawerOpen,
            );
        }
        if (toggle) {
            toggle.setAttribute(
                "aria-expanded",
                runtimeState.chatConversationDrawerOpen ? "true" : "false",
            );
        }
    }

    function canToggleChatConversationDrawer() {
        return window.innerWidth <= 768;
    }

    function syncChatBusyControls() {
        const sendButton = get("btnRuntimeChatSend");
        if (sendButton) {
            sendButton.disabled = !!runtimeState.activeJobId;
            sendButton.classList.toggle("is-loading", !!runtimeState.chatBusy);
            sendButton.setAttribute(
                "aria-busy",
                runtimeState.chatBusy ? "true" : "false",
            );
        }
    }

    async function loadChatConversations({ selectFirst = true } = {}) {
        if (runtimeState.chatConversationsLoading) return;
        runtimeState.chatConversationsLoading = true;
        try {
            const data = await fetchJsonOrThrow(
                "/api/runtime/chat/conversations",
            );
            runtimeState.chatConversations = Array.isArray(data.conversations)
                ? data.conversations
                : [];
            const activeJob =
                data && data.active_job && data.active_job.job_id
                    ? data.active_job
                    : null;
            if (activeJob && activeJob.conversation_id) {
                runtimeState.activeJobId = String(activeJob.job_id || "");
                runtimeState.chatBusy = true;
                runtimeState.activeJobConversationId = String(
                    activeJob.conversation_id,
                );
                runtimeState.currentChatConversationId =
                    runtimeState.activeJobConversationId;
            }
            if (
                selectFirst &&
                !runtimeState.currentChatConversationId &&
                runtimeState.chatConversations.length
            ) {
                runtimeState.currentChatConversationId = String(
                    runtimeState.chatConversations[0].id || "",
                );
            }
            runtimeState.chatConversationsLoaded = true;
            renderChatConversationList();
            if (!runtimeState.chatConversations.length && selectFirst) {
                await createChatConversation({ switchTo: true });
            }
        } finally {
            runtimeState.chatConversationsLoading = false;
        }
    }

    async function createChatConversation({ switchTo = true } = {}) {
        if (runtimeState.chatBusy || runtimeState.activeJobId) {
            showToast(t("runtime.chat_running"), "warning", 3000);
            return null;
        }
        const data = await fetchJsonOrThrow("/api/runtime/chat/conversations", {
            method: "POST",
            body: JSON.stringify({}),
        });
        const conversation =
            data && data.conversation ? data.conversation : null;
        if (!conversation || !conversation.id) return null;
        runtimeState.chatConversations = [
            conversation,
            ...runtimeState.chatConversations.filter(
                (item) => String(item.id) !== String(conversation.id),
            ),
        ];
        runtimeState.recentlyCreatedConversationId = String(conversation.id);
        if (switchTo) {
            await switchChatConversation(String(conversation.id));
            setChatConversationDrawerOpen(false);
        } else {
            renderChatConversationList();
        }
        showToast(t("runtime.chat_conversation_created"), "success", 1800);
        window.setTimeout(() => {
            if (
                runtimeState.recentlyCreatedConversationId ===
                String(conversation.id)
            ) {
                runtimeState.recentlyCreatedConversationId = "";
                renderChatConversationList();
            }
        }, 1300);
        return conversation;
    }

    async function renameChatConversation(conversationId) {
        const id = String(conversationId || "").trim();
        if (!id) return;
        const current = runtimeState.chatConversations.find(
            (item) => String(item.id) === id,
        );
        const nextTitle = window.prompt(
            t("runtime.chat_rename_conversation"),
            current ? chatConversationTitle(current) : "",
        );
        if (nextTitle === null) return;
        const title = String(nextTitle || "").trim();
        if (!title) return;
        const data = await fetchJsonOrThrow(
            `/api/runtime/chat/conversations/${encodeURIComponent(id)}`,
            {
                method: "PATCH",
                body: JSON.stringify({ title }),
            },
        );
        const updated = data && data.conversation ? data.conversation : null;
        if (updated && updated.id) {
            runtimeState.chatConversations = runtimeState.chatConversations.map(
                (item) =>
                    String(item.id) === String(updated.id) ? updated : item,
            );
            renderChatConversationList();
        }
    }

    async function deleteChatConversation(conversationId) {
        const id = String(conversationId || "").trim();
        if (!id) return;
        if (runtimeState.chatBusy || runtimeState.activeJobId) {
            showToast(t("runtime.chat_running"), "warning", 3000);
            return;
        }
        if (!window.confirm(t("runtime.chat_delete_confirm"))) return;
        await fetchJsonOrThrow(
            `/api/runtime/chat/conversations/${encodeURIComponent(id)}`,
            { method: "DELETE" },
        );
        runtimeState.chatConversations = runtimeState.chatConversations.filter(
            (item) => String(item.id) !== id,
        );
        if (currentChatConversationId() === id) {
            const next = runtimeState.chatConversations[0];
            if (next && next.id) {
                await switchChatConversation(String(next.id));
            } else {
                runtimeState.currentChatConversationId = "";
                resetChatConversationState();
                clearChatMessages();
                renderChatConversationList();
            }
        } else {
            renderChatConversationList();
        }
        setChatConversationDrawerOpen(false);
    }

    function resetChatConversationState() {
        runtimeState.chatHistoryLoaded = false;
        runtimeState.chatHistoryCursor = null;
        runtimeState.chatHistoryHasMore = false;
        runtimeState.chatHistoryLoading = false;
        runtimeState.chatTopLoadSuppressedUntil = 0;
        runtimeState.lastEventSeq = 0;
        runtimeState.streamingMessageId = null;
        runtimeState.activeChatMessageId = null;
        runtimeState.toolBlocks.clear();
        clearToolCollapseTimers();
        hideSelectionQuoteButton();
        clearChatAttachments();
        clearChatReferences();
        const input = get("runtimeChatInput");
        if (input) input.value = "";
    }

    async function switchChatConversation(conversationId) {
        const id = String(conversationId || "").trim();
        if (!id) return;
        if (id === currentChatConversationId()) {
            setChatConversationDrawerOpen(false);
            return;
        }
        if (
            runtimeState.activeJobId &&
            runtimeState.activeJobConversationId !== id
        ) {
            runtimeState.currentChatConversationId = id;
            resetChatConversationState();
            clearChatMessages();
            renderChatConversationList();
            await loadChatHistory(true);
            syncChatBusyControls();
            setChatConversationDrawerOpen(false);
            return;
        }
        stopChatPolling();
        stopChatClock();
        runtimeState.currentChatConversationId = id;
        if (!runtimeState.activeJobId) {
            runtimeState.activeJobConversationId = "";
            runtimeState.chatBusy = false;
        }
        setButtonLoading(get("btnRuntimeChatSend"), false);
        resetChatConversationState();
        clearChatMessages();
        renderChatConversationList();
        await loadChatHistory(true);
        if (
            runtimeState.activeJobId &&
            runtimeState.activeJobConversationId === id
        ) {
            ensureStreamingMessage(runtimeState.activeJobId);
            attachChatJob(
                runtimeState.activeJobId,
                runtimeState.lastEventSeq,
            ).catch(() => {});
        }
        syncChatBusyControls();
        setChatConversationDrawerOpen(false);
    }

    async function loadChatHistory(force = false) {
        if (!currentChatConversationId()) {
            await loadChatConversations();
        }
        if (!currentChatConversationId()) return;
        if (runtimeState.chatHistoryLoaded && !force) return;
        runtimeState.chatHistoryLoading = true;
        const res = await api(
            chatUrl("/api/runtime/chat/history", { limit: 50 }),
        );
        const data = await parseJsonSafe(res);
        if (!res.ok || (data && data.error)) {
            runtimeState.chatHistoryLoading = false;
            throw new Error(buildRequestError(res, data));
        }

        clearChatMessages();
        const items = data && Array.isArray(data.items) ? data.items : [];
        items.forEach((item) => {
            appendHistoryChatItem(item, { scroll: false });
        });
        runtimeState.chatHistoryCursor =
            data && data.next_before !== undefined ? data.next_before : null;
        runtimeState.chatHistoryHasMore = !!(data && data.has_more);
        runtimeState.chatHistoryLoaded = true;
        runtimeState.chatHistoryLoading = false;
        forceScrollChatToBottomSoon();
        await resumeActiveChatJob();
    }

    async function loadOlderChatHistory() {
        const log = get("runtimeChatLog");
        if (
            !log ||
            runtimeState.chatHistoryLoading ||
            !runtimeState.chatHistoryHasMore ||
            isChatTopHistoryLoadSuppressed()
        )
            return;
        runtimeState.chatHistoryLoading = true;
        const loader = get("runtimeChatLoadMore");
        if (loader) loader.textContent = t("runtime.chat_loading_more");
        const previousHeight = log.scrollHeight;
        const before = runtimeState.chatHistoryCursor;
        try {
            const res = await api(
                chatUrl("/api/runtime/chat/history", {
                    limit: 50,
                    before,
                }),
            );
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            const items = data && Array.isArray(data.items) ? data.items : [];
            for (let idx = items.length - 1; idx >= 0; idx -= 1) {
                appendHistoryChatItem(items[idx], {
                    prepend: true,
                    scroll: false,
                });
            }
            runtimeState.chatHistoryCursor =
                data && data.next_before !== undefined
                    ? data.next_before
                    : null;
            runtimeState.chatHistoryHasMore = !!(data && data.has_more);
            log.scrollTop = log.scrollHeight - previousHeight;
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
            );
        } finally {
            runtimeState.chatHistoryLoading = false;
            if (loader) loader.textContent = "";
        }
    }

    function applyChatEvent(event, payload, seq = 0) {
        if (seq)
            runtimeState.lastEventSeq = Math.max(
                runtimeState.lastEventSeq,
                seq,
            );
        const eventJobId =
            payload && payload.job_id ? String(payload.job_id) : "";
        const eventConversationId =
            payload && payload.conversation_id
                ? String(payload.conversation_id)
                : "";
        const eventForCurrentConversation =
            !eventConversationId ||
            eventConversationId === currentChatConversationId();
        if (event === "meta") {
            if (payload && payload.job_id) {
                runtimeState.activeJobId = String(payload.job_id);
                runtimeState.activeJobConversationId = String(
                    payload.conversation_id || currentChatConversationId(),
                );
                const existing = findActiveChatMessage(
                    runtimeState.activeJobId,
                );
                if (existing) existing.dataset.jobId = runtimeState.activeJobId;
            }
            return;
        }
        if (!eventForCurrentConversation) {
            if (
                (event === "done" || event === "error") &&
                (!eventJobId || eventJobId === runtimeState.activeJobId)
            ) {
                stopChatPolling();
                runtimeState.activeJobId = null;
                runtimeState.activeJobConversationId = "";
                runtimeState.chatBusy = false;
                setButtonLoading(get("btnRuntimeChatSend"), false);
                syncChatBusyControls();
                loadChatConversations({ selectFirst: false }).catch(() => {});
            }
            return;
        }
        if (event === "stage") {
            const item = ensureStreamingMessage(eventJobId);
            if (!item) return;
            setChatStage(item, payload || {});
            return;
        }
        if (event === "agent_stage") {
            upsertAgentStageBlock(payload || {}, eventJobId, seq);
            return;
        }
        if (
            event === "tool_start" ||
            event === "tool_end" ||
            event === "agent_start" ||
            event === "agent_end"
        ) {
            upsertToolBlock(payload || {}, event, eventJobId);
            return;
        }
        if (event === "message") {
            const content = String(
                payload && (payload.content ?? payload.message)
                    ? (payload.content ?? payload.message)
                    : "",
            ).trim();
            if (!content) return;
            const item = ensureStreamingMessage(eventJobId);
            if (!item) return;
            const nested = appendNestedTimelineMessage(
                item,
                runtimeState.toolBlocks,
                payload || {},
                content,
            );
            if (!nested) appendTimelineMessage(item, content, "bot");
            finishStreamingMessage();
            scrollChatToBottomSoon();
            return;
        }
        if (event === "done") {
            stopChatPolling();
            if (
                payload &&
                payload.reply &&
                runtimeState.streamingMessageId &&
                !(
                    document.querySelector(
                        `[data-message-id="${CSS.escape(runtimeState.streamingMessageId)}"]`,
                    )?.dataset.rawContent || ""
                ).trim()
            ) {
                const item = ensureStreamingMessage(eventJobId);
                if (item) {
                    const content = String(payload.reply);
                    appendTimelineMessage(item, content, "bot");
                    scrollChatToBottomSoon();
                }
            }
            finalizeActiveChatMessage(payload || {});
            runtimeState.activeJobId = null;
            runtimeState.activeJobConversationId = "";
            runtimeState.chatBusy = false;
            runtimeState.chatHistoryLoaded = true;
            setButtonLoading(get("btnRuntimeChatSend"), false);
            syncChatBusyControls();
            loadChatConversations({ selectFirst: false }).catch(() => {});
            return;
        }
        if (event === "error") {
            stopChatPolling();
            finalizeActiveChatMessage();
            runtimeState.activeJobId = null;
            runtimeState.activeJobConversationId = "";
            runtimeState.chatBusy = false;
            setButtonLoading(get("btnRuntimeChatSend"), false);
            syncChatBusyControls();
            const message = String(
                payload && (payload.error || payload.message)
                    ? payload.error || payload.message
                    : "stream error",
            );
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(message)}`,
                "error",
                5000,
            );
        }
    }

    function applyChatEventsPayload(data, jobId) {
        const events = data && Array.isArray(data.events) ? data.events : [];
        events
            .filter((entry) => entry && typeof entry === "object")
            .sort((a, b) => Number(a.seq || 0) - Number(b.seq || 0))
            .forEach((entry) => {
                applyChatEvent(
                    String(entry.event || ""),
                    entry.payload || {},
                    Number(entry.seq || 0),
                );
            });
        const job = data && data.job ? data.job : null;
        applyChatJobSnapshot(job, jobId);
        if (
            job &&
            runtimeState.activeJobId === jobId &&
            ["done", "error", "cancelled"].includes(String(job.status || ""))
        ) {
            applyChatEvent(
                job.status === "done" ? "done" : "error",
                job.status === "done"
                    ? job
                    : {
                          error: job.error || job.status,
                          job_id: job.job_id || jobId,
                          conversation_id: job.conversation_id || "",
                          duration_ms: job.duration_ms,
                      },
                Number(job.last_seq || runtimeState.lastEventSeq),
            );
        }
    }

    function applyChatJobSnapshot(job, jobId) {
        if (!job || runtimeState.activeJobId !== jobId) return;
        const jobConversationId = String(job.conversation_id || "").trim();
        if (
            jobConversationId &&
            jobConversationId !== currentChatConversationId()
        ) {
            return;
        }
        const item = ensureStreamingMessage(jobId);
        if (!item) return;
        const status = String(job.status || "");
        if (!["done", "error", "cancelled"].includes(status)) {
            const stage = String(job.current_stage || "").trim();
            if (stage) {
                setChatStage(item, {
                    stage,
                    detail: job.current_stage_detail || "",
                    elapsed_ms: job.elapsed_ms,
                });
            }
        }
        const toolCalls = Array.isArray(job.current_tool_calls)
            ? job.current_tool_calls
            : [];
        toolCalls.forEach((payload) => {
            upsertToolSnapshot(payload || {}, jobId);
        });
        const agentStages = Array.isArray(job.current_agent_stages)
            ? job.current_agent_stages
            : [];
        agentStages.forEach((payload) => {
            upsertAgentStageBlock(
                payload || {},
                jobId,
                Number(job.last_seq || 0),
            );
        });
    }

    async function pollChatJob(jobId) {
        if (runtimeState.activeJobId !== jobId) return;
        runtimeState.chatBusy = true;
        setButtonLoading(get("btnRuntimeChatSend"), true);
        syncChatBusyControls();
        try {
            const data = await fetchJsonOrThrow([
                ...runtimeChatJobEventsUrls(jobId, {
                    after: String(runtimeState.lastEventSeq),
                    format: "json",
                }),
            ]);
            runtimeState.chatPollBackoffMs = CHAT_POLL_INTERVAL_MS;
            applyChatEventsPayload(data, jobId);
        } catch (error) {
            if (runtimeState.activeJobId === jobId) {
                showToast(t("runtime.chat_reconnecting"), "warning", 1800);
                runtimeState.chatPollBackoffMs = Math.min(
                    8000,
                    Math.max(
                        CHAT_POLL_INTERVAL_MS,
                        runtimeState.chatPollBackoffMs * 1.6,
                    ),
                );
            } else {
                showToast(
                    `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                    "error",
                    5000,
                );
            }
        }
        if (runtimeState.activeJobId !== jobId || !runtimeState.chatBusy) {
            stopChatPolling();
            return;
        }
        stopChatPolling();
        runtimeState.chatPollTimer = setTimeout(() => {
            pollChatJob(jobId).catch(() => {});
        }, runtimeState.chatPollBackoffMs);
    }

    async function attachChatJob(jobId, after = 0) {
        stopChatPolling();
        runtimeState.activeJobId = jobId;
        runtimeState.activeJobConversationId =
            runtimeState.activeJobConversationId || currentChatConversationId();
        runtimeState.lastEventSeq = Number(after || 0);
        runtimeState.chatBusy = true;
        runtimeState.chatPollBackoffMs = CHAT_POLL_INTERVAL_MS;
        startChatClock();
        setButtonLoading(get("btnRuntimeChatSend"), true);
        syncChatBusyControls();
        pollChatJob(jobId).catch(() => {});
    }

    async function resumeActiveChatJob() {
        if (runtimeState.activeJobId) return;
        try {
            const data = await fetchJsonOrThrow(
                chatUrl("/api/runtime/chat/jobs/active"),
            );
            const job = data && data.job ? data.job : null;
            if (!job || !job.job_id) {
                stopActiveJobResumeTimer();
                runtimeState.activeJobResumeAttempts = 0;
                return;
            }
            stopActiveJobResumeTimer();
            runtimeState.activeJobResumeAttempts = 0;
            if (job.conversation_id) {
                runtimeState.currentChatConversationId = String(
                    job.conversation_id,
                );
                runtimeState.activeJobConversationId = String(
                    job.conversation_id,
                );
                renderChatConversationList();
            }
            runtimeState.activeJobId = String(job.job_id);
            ensureStreamingMessage(runtimeState.activeJobId);
            attachChatJob(
                runtimeState.activeJobId,
                runtimeState.lastEventSeq,
            ).catch(() => {});
        } catch (_error) {
            if (runtimeState.activeJobId) return;
            runtimeState.activeJobResumeAttempts += 1;
            if (
                runtimeState.activeJobResumeAttempts >
                ACTIVE_JOB_RESUME_MAX_ATTEMPTS
            ) {
                stopActiveJobResumeTimer();
                return;
            }
            const delay = Math.min(
                8000,
                1000 * runtimeState.activeJobResumeAttempts,
            );
            stopActiveJobResumeTimer();
            runtimeState.activeJobResumeTimer = setTimeout(() => {
                resumeActiveChatJob().catch(() => {});
            }, delay);
        }
    }

    async function clearChatHistory() {
        if (runtimeState.chatBusy || runtimeState.activeJobId) {
            showToast(t("runtime.chat_running"), "warning", 3000);
            return;
        }
        if (!window.confirm(t("runtime.chat_clear_confirm"))) return;
        try {
            const res = await api(chatUrl("/api/runtime/chat/history"), {
                method: "DELETE",
            });
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            clearChatMessages();
            runtimeState.chatHistoryLoaded = true;
            runtimeState.chatHistoryCursor = null;
            runtimeState.chatHistoryHasMore = false;
            stopChatPolling();
            loadChatConversations({ selectFirst: false }).catch(() => {});
            showToast(t("runtime.chat_cleared"), "success", 2200);
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
            );
        }
    }

    async function sendChatMessage() {
        if (runtimeState.chatBusy) return;
        const input = get("runtimeChatInput");
        const button = get("btnRuntimeChatSend");
        if (!input) return;
        if (!currentChatConversationId()) {
            await createChatConversation({ switchTo: true });
        }
        if (!currentChatConversationId()) return;
        const message = (input.value || "").trim();
        const attachments = [...runtimeState.chatAttachments];
        const references = [...runtimeState.chatReferences];
        if (!message && !attachments.length && !references.length) return;

        runtimeState.chatBusy = true;
        setButtonLoading(button, true);

        try {
            const outboundMessage = await buildChatMessageWithAttachments(
                message,
                attachments,
                references,
            );
            if (!outboundMessage) {
                throw new Error("message is required");
            }
            clearToolCollapseTimers();
            stopChatPolling();
            stopChatClock();
            runtimeState.toolBlocks.clear();
            runtimeState.streamingMessageId = null;
            runtimeState.activeChatMessageId = null;
            runtimeState.lastEventSeq = 0;
            appendChatMessage("user", outboundMessage);
            input.value = "";
            clearChatAttachments();
            clearChatReferences();
            forceScrollChatToBottomSoon();

            const res = await api("/api/runtime/chat/jobs", {
                method: "POST",
                body: JSON.stringify({
                    message: outboundMessage,
                    conversation_id: currentChatConversationId(),
                }),
            });
            const data = await parseJsonSafe(res);
            if (!res.ok || (data && data.error)) {
                throw new Error(buildRequestError(res, data));
            }
            const jobId = data && data.job_id ? String(data.job_id) : "";
            if (!jobId) {
                throw new Error("missing job_id");
            }
            ensureStreamingMessage();
            forceScrollChatToBottomSoon();
            await attachChatJob(jobId, 0);
        } catch (error) {
            runtimeState.chatBusy = false;
            setButtonLoading(button, false);
            syncChatBusyControls();
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
            );
        }
    }

    function handleChatFilesPicked(event) {
        const input = event && event.target ? event.target : null;
        const files = input && input.files ? Array.from(input.files) : [];
        const chatInput = get("runtimeChatInput");
        if (!chatInput || files.length === 0) return;

        try {
            addChatFiles(files, { source: "picker" });
            chatInput.focus();
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
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
                5000,
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
                5000,
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
        if (memoryRefresh)
            memoryRefresh.addEventListener("click", refreshMemory);

        const memoryCreateBtn = get("btnMemoryCreate");
        if (memoryCreateBtn)
            memoryCreateBtn.addEventListener("click", createMemory);

        const runMemorySearch = () =>
            runQueryAction("memory", "btnRuntimeMemorySearch", searchMemory);
        const runEventsSearch = () =>
            runQueryAction("events", "btnRuntimeEventsSearch", searchEvents);
        const runProfilesSearch = () =>
            runQueryAction(
                "profiles",
                "btnRuntimeProfilesSearch",
                searchProfiles,
            );
        const runProfileGet = () =>
            runQueryAction(
                "profileGet",
                "btnRuntimeProfileGet",
                fetchProfileByEntity,
            );

        const memoryBtn = get("btnRuntimeMemorySearch");
        if (memoryBtn) memoryBtn.addEventListener("click", runMemorySearch);
        bindEnterMany(
            [
                "runtimeMemoryQuery",
                "runtimeMemoryTopK",
                "runtimeMemoryTimeFrom",
                "runtimeMemoryTimeTo",
            ],
            runMemorySearch,
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
            runEventsSearch,
        );

        const profilesBtn = get("btnRuntimeProfilesSearch");
        if (profilesBtn)
            profilesBtn.addEventListener("click", runProfilesSearch);
        bindEnterMany(
            [
                "runtimeProfilesQuery",
                "runtimeProfilesTopK",
                "runtimeProfilesEntityType",
            ],
            runProfilesSearch,
        );

        const profileGetBtn = get("btnRuntimeProfileGet");
        if (profileGetBtn)
            profileGetBtn.addEventListener("click", runProfileGet);
        bindEnter("runtimeProfileEntityType", runProfileGet);
        bindEnter("runtimeProfileEntityId", runProfileGet);

        const sendBtn = get("btnRuntimeChatSend");
        if (sendBtn) sendBtn.addEventListener("click", sendChatMessage);

        const newChatBtn = get("btnRuntimeChatNew");
        if (newChatBtn) {
            newChatBtn.addEventListener("click", () => {
                createChatConversation({ switchTo: true }).catch((error) => {
                    showToast(
                        `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                        "error",
                        5000,
                    );
                });
            });
        }

        const conversationDrawerToggle = get(
            "runtimeChatConversationDrawerToggle",
        );
        if (conversationDrawerToggle) {
            conversationDrawerToggle.addEventListener("click", () => {
                if (!canToggleChatConversationDrawer()) return;
                const shouldOpen = !runtimeState.chatConversationDrawerOpen;
                setChatConversationDrawerOpen(shouldOpen);
            });
        }

        setChatAutoScroll(readChatAutoScrollPreference(), {
            persist: false,
        });
        const autoScrollToggle = get("runtimeChatAutoScroll");
        if (autoScrollToggle) {
            autoScrollToggle.addEventListener("change", () => {
                setChatAutoScroll(autoScrollToggle.checked);
            });
        }

        const chatLog = get("runtimeChatLog");
        const conversationList = get("runtimeChatConversations");
        if (conversationList) {
            conversationList.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                const selectButton = target.closest(
                    "[data-conversation-select]",
                );
                if (selectButton) {
                    switchChatConversation(
                        selectButton.getAttribute("data-conversation-select"),
                    ).catch((error) => {
                        showToast(
                            `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                            "error",
                            5000,
                        );
                    });
                    return;
                }
                const renameButton = target.closest(
                    "[data-conversation-rename]",
                );
                if (renameButton) {
                    renameChatConversation(
                        renameButton.getAttribute("data-conversation-rename"),
                    ).catch((error) => {
                        showToast(
                            `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                            "error",
                            5000,
                        );
                    });
                    return;
                }
                const deleteButton = target.closest(
                    "[data-conversation-delete]",
                );
                if (deleteButton) {
                    deleteChatConversation(
                        deleteButton.getAttribute("data-conversation-delete"),
                    ).catch((error) => {
                        showToast(
                            `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                            "error",
                            5000,
                        );
                    });
                }
            });
        }
        if (chatLog) {
            chatLog.addEventListener("scroll", () => {
                if (isChatTopHistoryLoadSuppressed()) return;
                if (chatLog.scrollTop <= 32) {
                    loadOlderChatHistory();
                }
            });
            chatLog.addEventListener("click", (event) => {
                const target = event.target;
                if (!(target instanceof Element)) return;
                const toggleButton = target.closest("[data-code-toggle]");
                if (toggleButton) {
                    const block = toggleButton.closest(".runtime-code-block");
                    if (block) toggleCodeBlock(block);
                    return;
                }
                const copyButton = target.closest("[data-code-copy]");
                if (copyButton) {
                    const block = copyButton.closest(".runtime-code-block");
                    if (block) copyCodeBlock(block);
                    return;
                }
                const runButton = target.closest("[data-code-run-html]");
                if (runButton) {
                    const block = runButton.closest(".runtime-code-block");
                    if (block) runHtmlCodeBlock(block);
                    return;
                }
                const quoteButton = target.closest("[data-quote-message]");
                if (quoteButton) {
                    const item = quoteButton.closest(".runtime-chat-item.bot");
                    const text = chatMessageTextForQuote(item);
                    if (text) addChatReference({ type: "message", text });
                }
            });
            chatLog.addEventListener("mouseup", () => {
                setTimeout(maybeShowSelectionQuoteButton, 0);
            });
            chatLog.addEventListener("keyup", () => {
                setTimeout(maybeShowSelectionQuoteButton, 0);
            });
        }

        const attachBtn = get("btnRuntimeChatImage");
        const fileInput = get("runtimeChatFileInput");
        if (attachBtn && fileInput) {
            attachBtn.addEventListener("click", () => {
                fileInput.click();
            });
            fileInput.addEventListener("change", handleChatFilesPicked);
        }

        const chatInput = get("runtimeChatInput");
        if (chatInput) {
            chatInput.addEventListener("focus", hideSelectionQuoteButton);
            chatInput.addEventListener("keydown", (event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    sendChatMessage();
                }
            });
            chatInput.addEventListener("paste", (event) => {
                const files =
                    event.clipboardData && event.clipboardData.files
                        ? Array.from(event.clipboardData.files)
                        : [];
                if (!files.length) return;
                event.preventDefault();
                addChatFiles(files, { source: "paste" });
            });
        }
        const inputRow = document.querySelector(".runtime-chat-input-row");
        if (inputRow) {
            inputRow.addEventListener("dragover", (event) => {
                event.preventDefault();
            });
            inputRow.addEventListener("drop", (event) => {
                const files =
                    event.dataTransfer && event.dataTransfer.files
                        ? Array.from(event.dataTransfer.files)
                        : [];
                if (!files.length) return;
                event.preventDefault();
                addChatFiles(files, { source: "drop" });
                if (chatInput) chatInput.focus();
            });
        }

        const htmlRunnerClose = get("btnRuntimeHtmlClose");
        if (htmlRunnerClose) {
            htmlRunnerClose.addEventListener("click", closeHtmlRunner);
        }
        const htmlRunnerPick = get("btnRuntimeHtmlPick");
        if (htmlRunnerPick) {
            htmlRunnerPick.addEventListener("click", () => {
                setHtmlRunnerPickMode(!runtimeState.htmlRunnerPickMode);
            });
        }
        const htmlRunnerToolbar = document.querySelector(
            ".runtime-html-runner-toolbar",
        );
        if (htmlRunnerToolbar) {
            htmlRunnerToolbar.addEventListener(
                "pointerdown",
                startHtmlRunnerDrag,
            );
            htmlRunnerToolbar.addEventListener(
                "pointermove",
                moveHtmlRunnerDrag,
            );
            htmlRunnerToolbar.addEventListener("pointerup", stopHtmlRunnerDrag);
            htmlRunnerToolbar.addEventListener(
                "pointercancel",
                stopHtmlRunnerDrag,
            );
            htmlRunnerToolbar.addEventListener(
                "lostpointercapture",
                stopHtmlRunnerDrag,
            );
        }
        const htmlRunnerFrame = get("runtimeHtmlRunnerFrame");
        if (htmlRunnerFrame) {
            htmlRunnerFrame.addEventListener("load", () => {
                syncHtmlRunnerPickModeToFrame();
            });
        }
        const htmlRunnerResize = get("runtimeHtmlRunnerResize");
        if (htmlRunnerResize) {
            htmlRunnerResize.addEventListener(
                "pointerdown",
                startHtmlRunnerResize,
            );
            htmlRunnerResize.addEventListener(
                "pointermove",
                moveHtmlRunnerResize,
            );
            htmlRunnerResize.addEventListener(
                "pointerup",
                stopHtmlRunnerResize,
            );
            htmlRunnerResize.addEventListener(
                "pointercancel",
                stopHtmlRunnerResize,
            );
            htmlRunnerResize.addEventListener(
                "lostpointercapture",
                stopHtmlRunnerResize,
            );
        }
        window.addEventListener("pointerup", (event) => {
            clearHtmlRunnerInteraction(event.pointerId);
        });
        window.addEventListener("pointercancel", (event) => {
            clearHtmlRunnerInteraction(event.pointerId);
        });
        window.addEventListener("blur", () => {
            clearHtmlRunnerInteraction();
        });
        window.addEventListener("message", (event) => {
            const frame = get("runtimeHtmlRunnerFrame");
            if (!frame || event.source !== frame.contentWindow) return;
            const data = event.data;
            if (!data) return;
            if (data.type === "webui-html-picker-ready") {
                syncHtmlRunnerPickModeToFrame();
                return;
            }
            if (data.type !== "webui-html-picked") return;
            handleHtmlRunnerPicked(data.html);
        });
        window.addEventListener("resize", clampVisibleHtmlRunner);
        window.addEventListener("resize", () => {
            if (window.innerWidth > 768) {
                setChatConversationDrawerOpen(false);
            }
        });
    }

    const PROBE_REFRESH_INTERVAL = 5000;

    function startProbeTimer() {
        stopProbeTimer();
        runtimeState.probeTimer = setInterval(
            refreshProbes,
            PROBE_REFRESH_INTERVAL,
        );
    }

    function stopProbeTimer() {
        if (runtimeState.probeTimer) {
            clearInterval(runtimeState.probeTimer);
            runtimeState.probeTimer = null;
        }
    }

    function onTabActivated(tab) {
        if (!state.authenticated) return;
        if (tab === "probes") {
            if (!runtimeState.probesLoaded) {
                refreshProbes();
            }
            startProbeTimer();
            return;
        }
        stopProbeTimer();
        if (tab === "memory") {
            if (!runtimeState.memoryLoaded) {
                refreshMemory();
            }
            return;
        }
        if (tab === "chat") {
            loadChatConversations()
                .then(() => loadChatHistory())
                .catch((error) => {
                    showToast(
                        `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                        "error",
                        5000,
                    );
                    resumeActiveChatJob().catch(() => {});
                });
            forceScrollChatToBottomSoon();
            window.addEventListener(
                "online",
                () => {
                    resumeActiveChatJob().catch(() => {});
                },
                { once: true },
            );
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
