(function () {
    const state = {
        initialized: false,
        loaded: false,
        loading: false,
        selectedUid: "",
        detail: null,
    };

    function formatBytes(value) {
        const size = Number(value || 0);
        if (!Number.isFinite(size) || size <= 0) return "0 B";
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        if (size < 1024 * 1024 * 1024)
            return `${(size / 1024 / 1024).toFixed(2)} MB`;
        return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
    }

    function parseBoolFilter(id) {
        const value = String(get(id)?.value || "").trim();
        if (!value) return null;
        return value === "true";
    }

    function setMeta(text) {
        const el = get("memesMeta");
        if (el) el.textContent = text || "";
    }

    function selectedRecord() {
        return state.detail && state.detail.record ? state.detail.record : null;
    }

    function detailInputValue(id, fallback = "") {
        return String(get(id)?.value || fallback || "").trim();
    }

    function renderStats(payload) {
        get("memesStatTotal").textContent = String(
            payload?.total_count ?? "--",
        );
        get("memesStatEnabled").textContent = String(
            payload?.enabled_count ?? "--",
        );
        get("memesStatAnimated").textContent = String(
            payload?.animated_count ?? "--",
        );
        get("memesStatPinned").textContent = String(
            payload?.pinned_count ?? "--",
        );
        get("memesStatBytes").textContent = formatBytes(
            payload?.total_bytes ?? 0,
        );
        const queue = payload?.queue || {};
        get("memesStatQueue").textContent =
            `${queue.pending ?? 0}/${queue.processing ?? 0}/${queue.failed ?? 0}`;
    }

    function renderList(payload) {
        const list = get("memesList");
        if (!list) return;
        const items = Array.isArray(payload?.items) ? payload.items : [];
        const total = Number(payload?.total || items.length || 0);
        const metaParts = [
            t("runtime.total").replace("{count}", String(total)),
        ];
        if (payload?.query_mode) metaParts.push(`mode=${payload.query_mode}`);
        if (payload?.keyword_query)
            metaParts.push(`keyword=${payload.keyword_query}`);
        if (payload?.semantic_query)
            metaParts.push(`semantic=${payload.semantic_query}`);
        setMeta(metaParts.join(" | "));
        if (!items.length) {
            list.innerHTML = `<div class="empty-state">${escapeHtml(t("runtime.empty"))}</div>`;
            return;
        }
        list.innerHTML = items
            .map((item) => {
                const tags = [];
                tags.push(
                    `<span class="runtime-tag">${item.enabled ? t("memes.enabled") : "disabled"}</span>`,
                );
                if (item.pinned)
                    tags.push(
                        `<span class="runtime-tag">${t("memes.pinned")}</span>`,
                    );
                if (item.is_animated)
                    tags.push(
                        `<span class="runtime-tag">${t("memes.animated")}</span>`,
                    );
                if (item.score != null)
                    tags.push(
                        `<span class="runtime-tag">score ${escapeHtml(String(item.score))}</span>`,
                    );
                if (item.keyword_score != null)
                    tags.push(
                        `<span class="runtime-tag">kw ${escapeHtml(String(item.keyword_score))}</span>`,
                    );
                if (item.semantic_score != null)
                    tags.push(
                        `<span class="runtime-tag">sem ${escapeHtml(String(item.semantic_score))}</span>`,
                    );
                if (item.rerank_score != null)
                    tags.push(
                        `<span class="runtime-tag">rerank ${escapeHtml(String(item.rerank_score))}</span>`,
                    );
                const desc = escapeHtml(item.description || "--");
                return `<button class="runtime-list-item meme-list-item ${state.selectedUid === item.uid ? "is-selected" : ""}" data-meme-uid="${escapeHtml(item.uid)}" type="button">
                    <div class="runtime-list-head"><code>${escapeHtml(item.uid)}</code><div class="runtime-tags">${tags.join("")}</div></div>
                    <div class="runtime-doc">${desc}</div>
                </button>`;
            })
            .join("");
        list.querySelectorAll("[data-meme-uid]").forEach((el) => {
            el.addEventListener("click", () => {
                loadDetail(el.getAttribute("data-meme-uid") || "");
            });
        });
    }

    function renderSources(sources) {
        const container = get("memesSources");
        if (!container) return;
        const items = Array.isArray(sources) ? sources : [];
        if (!items.length) {
            container.innerHTML = `<div class="empty-state">${escapeHtml(t("runtime.empty"))}</div>`;
            return;
        }
        container.innerHTML = items
            .map((item) => {
                const head = [
                    item.chat_type || "-",
                    item.chat_id || "-",
                    item.sender_id || "-",
                ]
                    .filter(Boolean)
                    .join(" / ");
                const doc = [
                    item.source_type || "-",
                    item.message_id ? `message ${item.message_id}` : "",
                    item.attachment_uid
                        ? `attachment ${item.attachment_uid}`
                        : "",
                    item.source_url || "",
                ]
                    .filter(Boolean)
                    .join(" | ");
                return `<div class="runtime-list-item">
                    <div class="runtime-list-head"><span>${escapeHtml(head)}</span><code>${escapeHtml(item.seen_at || "")}</code></div>
                    <div class="runtime-doc">${escapeHtml(doc || "--")}</div>
                </div>`;
            })
            .join("");
    }

    function renderDetail(payload) {
        state.detail = payload;
        const record = payload && payload.record ? payload.record : null;
        const empty = get("memesDetailEmpty");
        const panel = get("memesDetailPanel");
        if (!record) {
            if (empty) empty.style.display = "block";
            if (panel) panel.style.display = "none";
            return;
        }
        if (empty) empty.style.display = "none";
        if (panel) panel.style.display = "block";
        get("memesDetailUid").textContent = record.uid || "--";
        get("memesDetailState").textContent = record.status || "--";
        get("memesDetailPreview").src =
            record.preview_url || record.blob_url || "";
        get("memesDetailAutoDescription").value = record.auto_description || "";
        get("memesDetailManualDescription").value =
            record.manual_description || "";
        get("memesDetailTags").value = Array.isArray(record.tags)
            ? record.tags.join(", ")
            : "";
        get("memesDetailAliases").value = Array.isArray(record.aliases)
            ? record.aliases.join(", ")
            : "";
        get("memesDetailEnabled").checked = !!record.enabled;
        get("memesDetailPinned").checked = !!record.pinned;
        get("memesDetailAnimated").textContent = record.is_animated
            ? t("memes.animated")
            : t("memes.filter_animated_static");
        get("memesDetailUseCount").textContent = `use ${record.use_count ?? 0}`;
        get("memesDetailFileSize").textContent = formatBytes(
            record.file_size || 0,
        );
        renderSources(payload.sources);
    }

    async function fetchStats() {
        const response = await api("/api/v1/management/memes/stats");
        if (!response.ok) throw new Error(await response.text());
        const payload = await response.json();
        renderStats(payload);
    }

    async function fetchList() {
        const params = new URLSearchParams();
        const query = detailInputValue("memesSearchInput");
        const queryMode = String(
            get("memesQueryMode")?.value || "hybrid",
        ).trim();
        const keywordQuery = detailInputValue("memesKeywordQuery");
        const semanticQuery = detailInputValue("memesSemanticQuery");
        if (query) params.set("q", query);
        if (queryMode) params.set("query_mode", queryMode);
        if (keywordQuery) params.set("keyword_query", keywordQuery);
        if (semanticQuery) params.set("semantic_query", semanticQuery);
        const enabled = parseBoolFilter("memesEnabledFilter");
        const animated = parseBoolFilter("memesAnimatedFilter");
        const pinned = parseBoolFilter("memesPinnedFilter");
        const sort = String(get("memesSortSelect")?.value || "updated_at");
        const topK = String(get("memesTopK")?.value || "20").trim();
        const pageSize = String(get("memesPageSize")?.value || "50").trim();
        if (enabled !== null) params.set("enabled", String(enabled));
        if (animated !== null) params.set("animated", String(animated));
        if (pinned !== null) params.set("pinned", String(pinned));
        if (sort) params.set("sort", sort);
        if (topK) params.set("top_k", topK);
        if (pageSize) params.set("page_size", pageSize);
        const response = await api(
            `/api/v1/management/memes?${params.toString()}`,
        );
        if (!response.ok) throw new Error(await response.text());
        const payload = await response.json();
        renderList(payload);
        return payload;
    }

    async function refreshAll() {
        if (state.loading) return;
        state.loading = true;
        try {
            await fetchStats();
            await fetchList();
            if (state.selectedUid) {
                await loadDetail(state.selectedUid, { silent: true });
            }
            state.loaded = true;
        } catch (error) {
            showToast(
                String(error && error.message ? error.message : error),
                "error",
            );
        } finally {
            state.loading = false;
        }
    }

    async function loadDetail(uid, options = {}) {
        const targetUid = String(uid || "").trim();
        if (!targetUid) return;
        try {
            const response = await api(
                `/api/v1/management/memes/${encodeURIComponent(targetUid)}`,
            );
            if (!response.ok) throw new Error(await response.text());
            const payload = await response.json();
            state.selectedUid = targetUid;
            renderDetail(payload);
            if (!options.silent) {
                await fetchList();
            }
        } catch (error) {
            showToast(
                String(error && error.message ? error.message : error),
                "error",
            );
        }
    }

    async function saveDetail() {
        const record = selectedRecord();
        if (!record) {
            showToast(t("memes.select_prompt"), "warning");
            return;
        }
        const payload = {
            manual_description: detailInputValue(
                "memesDetailManualDescription",
            ),
            tags: detailInputValue("memesDetailTags"),
            aliases: detailInputValue("memesDetailAliases"),
            enabled: !!get("memesDetailEnabled").checked,
            pinned: !!get("memesDetailPinned").checked,
        };
        const response = await api(
            `/api/v1/management/memes/${encodeURIComponent(record.uid)}`,
            {
                method: "PATCH",
                body: JSON.stringify(payload),
            },
        );
        if (!response.ok) throw new Error(await response.text());
        showToast(t("memes.saved"), "success");
        await loadDetail(record.uid, { silent: true });
        await fetchStats();
        await fetchList();
    }

    async function queueAction(kind) {
        const record = selectedRecord();
        if (!record) {
            showToast(t("memes.select_prompt"), "warning");
            return;
        }
        const response = await api(
            `/api/v1/management/memes/${encodeURIComponent(record.uid)}/${kind}`,
            {
                method: "POST",
                body: JSON.stringify({}),
            },
        );
        if (!response.ok) throw new Error(await response.text());
        showToast(
            kind === "reanalyze"
                ? t("memes.reanalyze_queued")
                : t("memes.reindex_queued"),
            "success",
        );
        await fetchStats();
    }

    async function deleteSelected() {
        const record = selectedRecord();
        if (!record) {
            showToast(t("memes.select_prompt"), "warning");
            return;
        }
        if (!window.confirm(t("memes.confirm_delete"))) return;
        const response = await api(
            `/api/v1/management/memes/${encodeURIComponent(record.uid)}`,
            { method: "DELETE" },
        );
        if (!response.ok) throw new Error(await response.text());
        state.selectedUid = "";
        state.detail = null;
        renderDetail(null);
        showToast(t("memes.deleted"), "success");
        await fetchStats();
        await fetchList();
    }

    function bindEnter(id, handler) {
        const el = get(id);
        if (!el) return;
        el.addEventListener("keydown", (event) => {
            if (event.key !== "Enter") return;
            if (event.shiftKey) return;
            event.preventDefault();
            handler();
        });
    }

    const controller = {
        init() {
            if (state.initialized) return;
            state.initialized = true;
            get("btnMemesRefresh")?.addEventListener("click", refreshAll);
            get("btnMemesSearch")?.addEventListener("click", fetchList);
            get("btnMemesSave")?.addEventListener("click", () => {
                saveDetail().catch((error) => {
                    showToast(
                        String(error && error.message ? error.message : error),
                        "error",
                    );
                });
            });
            get("btnMemesReanalyze")?.addEventListener("click", () => {
                queueAction("reanalyze").catch((error) => {
                    showToast(
                        String(error && error.message ? error.message : error),
                        "error",
                    );
                });
            });
            get("btnMemesReindex")?.addEventListener("click", () => {
                queueAction("reindex").catch((error) => {
                    showToast(
                        String(error && error.message ? error.message : error),
                        "error",
                    );
                });
            });
            get("btnMemesDelete")?.addEventListener("click", () => {
                deleteSelected().catch((error) => {
                    showToast(
                        String(error && error.message ? error.message : error),
                        "error",
                    );
                });
            });
            bindEnter("memesSearchInput", () => {
                fetchList().catch((error) => {
                    showToast(
                        String(error && error.message ? error.message : error),
                        "error",
                    );
                });
            });
        },
        onTabActivated(tab) {
            if (tab !== "memes") return;
            if (!state.loaded) {
                refreshAll();
            }
        },
    };

    window.MemesController = controller;
})();
