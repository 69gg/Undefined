(function () {
    const runtimeState = {
        initialized: false,
        probesLoaded: false,
        memoryLoaded: false,
        runtimeMetaLoaded: false,
        runtimeEnabled: true,
        chatBusy: false,
        chatHistoryLoaded: false,
        activeJobId: null,
        lastEventSeq: 0,
        chatHistoryCursor: null,
        chatHistoryHasMore: false,
        chatHistoryLoading: false,
        streamingMessageId: null,
        activeChatMessageId: null,
        chatReconnectTimer: null,
        toolBlocks: new Map(),
        probeTimer: null,
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

    function appendChatMessage(role, content, options = {}) {
        const log = get("runtimeChatLog");
        if (!log) return null;
        const isBot = role !== "user";
        const contentClass = isBot
            ? "runtime-chat-content markdown"
            : "runtime-chat-content";
        const item = document.createElement("div");
        item.className = `runtime-chat-item ${role}`;
        if (options.id) item.dataset.messageId = options.id;
        if (options.jobId) item.dataset.jobId = options.jobId;
        item.innerHTML = `<div class="runtime-chat-role">${role === "user" ? "You" : "AI"}</div><div class="${contentClass}">${renderChatContent(content, isBot)}</div>`;
        if (options.prepend) {
            log.insertBefore(item, log.firstChild);
        } else {
            log.appendChild(item);
            if (options.scroll !== false) scrollChatToBottom();
        }
        return item;
    }

    function scrollChatToBottom() {
        const log = get("runtimeChatLog");
        if (!log) return;
        log.scrollTop = log.scrollHeight;
    }

    function updateChatMessage(item, content, role = "bot") {
        if (!item) return;
        const contentEl = item.querySelector(".runtime-chat-content");
        if (!contentEl) return;
        const isBot = role !== "user";
        contentEl.innerHTML = renderChatContent(content, isBot);
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

    function finishStreamingMessage() {
        if (!runtimeState.streamingMessageId) return;
        const item = document.querySelector(
            `[data-message-id="${CSS.escape(runtimeState.streamingMessageId)}"]`,
        );
        if (item) item.classList.remove("streaming");
        runtimeState.streamingMessageId = null;
    }

    function finalizeActiveChatMessage() {
        finishStreamingMessage();
        runtimeState.activeChatMessageId = null;
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

    function renderToolBlock(block) {
        const label = toolDisplayLabel(block);
        const statusLabel = toolStatusLabel(block);
        const args = block.argumentsPreview
            ? `<pre>${escapeHtml(block.argumentsPreview)}</pre>`
            : "";
        const result = block.resultPreview
            ? `<div class="runtime-tool-result">${escapeHtml(block.resultPreview)}</div>`
            : "";
        const openAttr = block.status === "running" ? " open" : "";
        const hintClass = block.uiHint
            ? ` ${escapeHtml(String(block.uiHint).replace(/_/g, "-"))}`
            : "";
        return (
            `<details class="runtime-tool-block ${escapeHtml(block.status)}${hintClass}"${openAttr}>` +
            `<summary><span>${escapeHtml(label)}</span><code>${escapeHtml(block.name || "--")}</code><em>${escapeHtml(statusLabel)}</em></summary>` +
            args +
            result +
            `</details>`
        );
    }

    function toolBlockKey(payload, blocks) {
        return (
            String(
                payload && payload.tool_call_id ? payload.tool_call_id : "",
            ) ||
            String(payload && payload.name ? payload.name : "") ||
            `tool-${blocks.size + 1}`
        );
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
        const previousUiHint = String(previous.uiHint || "");
        const nextUiHint = String(
            (payload && payload.ui_hint) || previousUiHint,
        );
        const nextArguments = String(
            (payload && payload.arguments_preview) ||
                previous.argumentsPreview ||
                "",
        );
        const block = {
            ...previous,
            name: String((payload && payload.name) || previous.name || ""),
            isAgent: !!(
                (payload && payload.is_agent) ||
                previous.isAgent ||
                status === "agent_start" ||
                status === "agent_end"
            ),
            status:
                status === "tool_end" || status === "agent_end"
                    ? payload && payload.ok === false
                        ? "error"
                        : "done"
                    : "running",
            argumentsPreview: nextArguments,
            resultPreview:
                nextUiHint === "webchat_private_send" ||
                nextUiHint === "webchat_end"
                    ? ""
                    : String(
                          (payload && payload.result_preview) ||
                              previous.resultPreview ||
                              "",
                      ),
            uiHint: nextUiHint,
        };
        blocks.set(key, block);
        return block;
    }

    function renderToolBlocks(blocks) {
        return Array.from(blocks.values()).map(renderToolBlock).join("");
    }

    function attachToolBlocks(item, blocks) {
        if (!item || !blocks || blocks.size === 0) return;
        let toolsEl = item.querySelector(".runtime-chat-tools");
        if (!toolsEl) {
            toolsEl = document.createElement("div");
            toolsEl.className = "runtime-chat-tools";
            const contentEl = item.querySelector(".runtime-chat-content");
            if (contentEl) {
                item.insertBefore(toolsEl, contentEl);
            } else {
                item.appendChild(toolsEl);
            }
        }
        toolsEl.innerHTML = renderToolBlocks(blocks);
    }

    function upsertToolBlock(payload, status, jobId = "") {
        reduceToolBlock(runtimeState.toolBlocks, payload, status);
        const item = ensureStreamingMessage(jobId);
        if (!item) return;
        attachToolBlocks(item, runtimeState.toolBlocks);
        scrollChatToBottom();
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
                event === "agent_end"
            );
        });
    }

    function renderHistoryToolBlocks(item) {
        const events = historyWebchatEvents(item);
        if (!events.length) return null;
        const blocks = new Map();
        events.forEach((entry) => {
            reduceToolBlock(blocks, entry.payload || {}, entry.event);
        });
        return blocks;
    }

    function appendHistoryChatItem(item, options = {}) {
        const role = item && item.role === "bot" ? "bot" : "user";
        const content = String((item && item.content) || "").trim();
        const blocks = role === "bot" ? renderHistoryToolBlocks(item) : null;
        if (!content && (!blocks || blocks.size === 0)) return null;
        const message = appendChatMessage(role, content, options);
        if (!message) return null;
        if (!content) message.classList.add("tool-only");
        if (blocks && blocks.size > 0) {
            attachToolBlocks(message, blocks);
        }
        return message;
    }

    function clearChatMessages() {
        const log = get("runtimeChatLog");
        if (!log) return;
        log.innerHTML = "";
        runtimeState.streamingMessageId = null;
        runtimeState.activeChatMessageId = null;
        runtimeState.toolBlocks.clear();
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
        if (useMarkdown && typeof marked !== "undefined" && marked.parse) {
            try {
                html = marked.parse(processed, { breaks: true, gfm: true });
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

    async function consumeSse(res, onEvent) {
        if (!res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        function emitBlock(rawBlock) {
            const block = String(rawBlock || "").trim();
            if (!block) return;
            let event = "message";
            let seq = 0;
            const dataLines = [];
            block.split("\n").forEach((line) => {
                if (line.startsWith(":")) return;
                if (line.startsWith("id:")) {
                    const parsed = Number(line.slice(3).trim());
                    seq = Number.isFinite(parsed) ? parsed : 0;
                    return;
                }
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
            onEvent(event, payload, seq);
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

    async function loadChatHistory(force = false) {
        if (runtimeState.chatHistoryLoaded && !force) return;
        runtimeState.chatHistoryLoading = true;
        const res = await api("/api/runtime/chat/history?limit=50");
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
        scrollChatToBottom();
        await resumeActiveChatJob();
    }

    async function loadOlderChatHistory() {
        const log = get("runtimeChatLog");
        if (
            !log ||
            runtimeState.chatHistoryLoading ||
            !runtimeState.chatHistoryHasMore
        )
            return;
        runtimeState.chatHistoryLoading = true;
        const loader = get("runtimeChatLoadMore");
        if (loader) loader.textContent = t("runtime.chat_loading_more");
        const previousHeight = log.scrollHeight;
        const before = runtimeState.chatHistoryCursor;
        try {
            const params = new URLSearchParams({ limit: "50" });
            if (before !== null && before !== undefined) {
                params.set("before", String(before));
            }
            const res = await api(
                `/api/runtime/chat/history?${params.toString()}`,
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
        if (event === "meta") {
            if (payload && payload.job_id) {
                runtimeState.activeJobId = String(payload.job_id);
                const existing = findActiveChatMessage(
                    runtimeState.activeJobId,
                );
                if (existing) existing.dataset.jobId = runtimeState.activeJobId;
            }
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
            item.dataset.rawContent = content;
            updateChatMessage(item, content, "bot");
            finishStreamingMessage();
            scrollChatToBottom();
            return;
        }
        if (event === "done") {
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
                    item.dataset.rawContent = content;
                    updateChatMessage(item, content, "bot");
                    scrollChatToBottom();
                }
            }
            finalizeActiveChatMessage();
            runtimeState.activeJobId = null;
            runtimeState.chatBusy = false;
            runtimeState.chatHistoryLoaded = true;
            setButtonLoading(get("btnRuntimeChatSend"), false);
            return;
        }
        if (event === "error") {
            finalizeActiveChatMessage();
            runtimeState.activeJobId = null;
            runtimeState.chatBusy = false;
            setButtonLoading(get("btnRuntimeChatSend"), false);
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

    async function attachChatJob(jobId, after = 0) {
        runtimeState.activeJobId = jobId;
        runtimeState.lastEventSeq = Number(after || 0);
        runtimeState.chatBusy = true;
        setButtonLoading(get("btnRuntimeChatSend"), true);
        try {
            const params = new URLSearchParams({
                after: String(runtimeState.lastEventSeq),
            });
            const res = await api(
                `/api/runtime/chat/jobs/${encodeURIComponent(jobId)}/events?${params.toString()}`,
                { headers: { Accept: "text/event-stream" } },
            );
            const contentType = (
                res.headers.get("Content-Type") || ""
            ).toLowerCase();
            if (
                !res.ok ||
                !contentType.includes("text/event-stream") ||
                !res.body
            ) {
                const data = await parseJsonSafe(res);
                throw new Error(buildRequestError(res, data));
            }
            await consumeSse(res, applyChatEvent);
            if (runtimeState.activeJobId === jobId && runtimeState.chatBusy) {
                const detail = await fetchJsonOrThrow(
                    `/api/runtime/chat/jobs/${encodeURIComponent(jobId)}`,
                );
                if (
                    detail &&
                    ["done", "error", "cancelled"].includes(detail.status)
                ) {
                    applyChatEvent(
                        detail.status === "done" ? "done" : "error",
                        detail.status === "done"
                            ? detail
                            : { error: detail.error || detail.status },
                        detail.last_seq || runtimeState.lastEventSeq,
                    );
                }
            }
        } catch (error) {
            if (runtimeState.activeJobId === jobId) {
                showToast(t("runtime.chat_reconnecting"), "warning", 1800);
                clearTimeout(runtimeState.chatReconnectTimer);
                runtimeState.chatReconnectTimer = setTimeout(() => {
                    attachChatJob(jobId, runtimeState.lastEventSeq).catch(
                        () => {},
                    );
                }, 1200);
            } else {
                showToast(
                    `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                    "error",
                    5000,
                );
            }
        }
    }

    async function resumeActiveChatJob() {
        if (runtimeState.activeJobId) return;
        try {
            const data = await fetchJsonOrThrow(
                "/api/runtime/chat/jobs/active",
            );
            const job = data && data.job ? data.job : null;
            if (!job || !job.job_id) return;
            runtimeState.activeJobId = String(job.job_id);
            attachChatJob(
                runtimeState.activeJobId,
                runtimeState.lastEventSeq,
            ).catch(() => {});
        } catch (_error) {
            // Runtime disabled/unreachable is surfaced by normal chat actions.
        }
    }

    async function clearChatHistory() {
        if (runtimeState.chatBusy || runtimeState.activeJobId) {
            showToast(t("runtime.chat_running"), "warning", 3000);
            return;
        }
        if (!window.confirm(t("runtime.chat_clear_confirm"))) return;
        const button = get("btnRuntimeChatClear");
        setButtonLoading(button, true);
        try {
            const res = await api("/api/runtime/chat/history", {
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
            showToast(t("runtime.chat_cleared"), "success", 2200);
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
            );
        } finally {
            setButtonLoading(button, false);
        }
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
        runtimeState.toolBlocks.clear();
        runtimeState.streamingMessageId = null;
        runtimeState.activeChatMessageId = null;
        runtimeState.lastEventSeq = 0;
        appendChatMessage("user", message);
        input.value = "";

        try {
            const res = await api("/api/runtime/chat/jobs", {
                method: "POST",
                body: JSON.stringify({ message }),
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
            await attachChatJob(jobId, 0);
        } catch (error) {
            runtimeState.chatBusy = false;
            setButtonLoading(button, false);
            showToast(
                `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                "error",
                5000,
            );
        }
    }

    async function handleChatImagePicked(event) {
        const input = event && event.target ? event.target : null;
        const files = input && input.files ? Array.from(input.files) : [];
        const chatInput = get("runtimeChatInput");
        if (!chatInput || files.length === 0) return;

        try {
            for (const file of files) {
                if (!file || !String(file.type || "").startsWith("image/"))
                    continue;
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

        const clearChatBtn = get("btnRuntimeChatClear");
        if (clearChatBtn)
            clearChatBtn.addEventListener("click", clearChatHistory);

        const chatLog = get("runtimeChatLog");
        if (chatLog) {
            chatLog.addEventListener("scroll", () => {
                if (chatLog.scrollTop <= 32) {
                    loadOlderChatHistory();
                }
            });
        }

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
            loadChatHistory().catch((error) => {
                showToast(
                    `${t("runtime.failed")}: ${appendRuntimeApiHint(error.message || error)}`,
                    "error",
                    5000,
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
