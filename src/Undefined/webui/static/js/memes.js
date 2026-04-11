(function () {
    const state = {
        initialized: false,
        loaded: false,
        loading: false,
        loadingMore: false,
        selectedUid: "",
        detail: null,
        listItems: [],
        total: 0,
        page: 0,
        pageSize: 50,
        hasMore: false,
        requestSeq: 0,
        queryKey: "",
        queryMeta: {
            queryMode: "",
            keywordQuery: "",
            semanticQuery: "",
            sort: "updated_at",
        },
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

    function showError(error) {
        showToast(
            String(error && error.message ? error.message : error),
            "error",
        );
    }

    function currentFilters() {
        return {
            query: detailInputValue("memesSearchInput"),
            queryMode: String(get("memesQueryMode")?.value || "hybrid").trim(),
            keywordQuery: detailInputValue("memesKeywordQuery"),
            semanticQuery: detailInputValue("memesSemanticQuery"),
            enabled: parseBoolFilter("memesEnabledFilter"),
            animated: parseBoolFilter("memesAnimatedFilter"),
            pinned: parseBoolFilter("memesPinnedFilter"),
            sort: String(get("memesSortSelect")?.value || "updated_at").trim(),
            topK: Math.max(
                1,
                Number.parseInt(
                    String(get("memesTopK")?.value || "20").trim(),
                    10,
                ) || 20,
            ),
            pageSize: Math.max(
                1,
                Math.min(
                    200,
                    Number.parseInt(
                        String(get("memesPageSize")?.value || "50").trim(),
                        10,
                    ) || 50,
                ),
            ),
        };
    }

    function buildQueryKey(filters) {
        return JSON.stringify({
            query: filters.query,
            queryMode: filters.queryMode,
            keywordQuery: filters.keywordQuery,
            semanticQuery: filters.semanticQuery,
            enabled: filters.enabled,
            animated: filters.animated,
            pinned: filters.pinned,
            sort: filters.sort,
            topK: filters.topK,
            pageSize: filters.pageSize,
        });
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

    function renderLoadMore() {
        const button = get("btnMemesLoadMore");
        if (!button) return;
        button.textContent = t("memes.load_more");
        button.disabled = state.loading || state.loadingMore;
        button.style.display =
            state.listItems.length > 0 && state.hasMore ? "" : "none";
    }

    function renderListMeta() {
        const metaParts = [
            t("runtime.total").replace("{count}", String(state.total || 0)),
            t("memes.loaded_meta")
                .replace("{loaded}", String(state.listItems.length))
                .replace("{total}", String(state.total || 0)),
        ];
        if (state.queryMeta.queryMode) {
            metaParts.push(`mode=${state.queryMeta.queryMode}`);
        }
        if (state.queryMeta.keywordQuery) {
            metaParts.push(`keyword=${state.queryMeta.keywordQuery}`);
        }
        if (state.queryMeta.semanticQuery) {
            metaParts.push(`semantic=${state.queryMeta.semanticQuery}`);
        }
        if (state.queryMeta.sort) {
            metaParts.push(`sort=${state.queryMeta.sort}`);
        }
        setMeta(metaParts.join(" | "));
    }

    function renderList() {
        const list = get("memesList");
        if (!list) return;
        renderListMeta();
        renderLoadMore();
        if (!state.listItems.length) {
            list.innerHTML = `<div class="empty-state">${escapeHtml(t("runtime.empty"))}</div>`;
            return;
        }
        list.innerHTML = state.listItems
            .map((item) => {
                const tags = [];
                tags.push(
                    `<span class="runtime-tag">${item.enabled ? t("memes.enabled") : "disabled"}</span>`,
                );
                if (item.pinned) {
                    tags.push(
                        `<span class="runtime-tag">${t("memes.pinned")}</span>`,
                    );
                }
                if (item.is_animated) {
                    tags.push(
                        `<span class="runtime-tag">${t("memes.animated")}</span>`,
                    );
                }
                if (item.use_count != null) {
                    tags.push(
                        `<span class="runtime-tag">use ${escapeHtml(String(item.use_count))}</span>`,
                    );
                }
                if (item.score != null) {
                    tags.push(
                        `<span class="runtime-tag">score ${escapeHtml(String(item.score))}</span>`,
                    );
                }
                if (item.keyword_score != null) {
                    tags.push(
                        `<span class="runtime-tag">kw ${escapeHtml(String(item.keyword_score))}</span>`,
                    );
                }
                if (item.semantic_score != null) {
                    tags.push(
                        `<span class="runtime-tag">sem ${escapeHtml(String(item.semantic_score))}</span>`,
                    );
                }
                if (item.rerank_score != null) {
                    tags.push(
                        `<span class="runtime-tag">rerank ${escapeHtml(String(item.rerank_score))}</span>`,
                    );
                }
                const desc = escapeHtml(item.description || "--");
                return `<button class="runtime-list-item meme-list-item ${state.selectedUid === item.uid ? "is-selected" : ""}" data-meme-uid="${escapeHtml(item.uid)}" type="button">
                    <div class="runtime-list-head"><code>${escapeHtml(item.uid)}</code><div class="runtime-tags">${tags.join("")}</div></div>
                    <div class="runtime-doc">${desc}</div>
                </button>`;
            })
            .join("");
        list.querySelectorAll("[data-meme-uid]").forEach((el) => {
            el.addEventListener("click", () => {
                loadDetail(el.getAttribute("data-meme-uid") || "").catch(
                    showError,
                );
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
        return payload;
    }

    async function fetchList(options = {}) {
        const append = !!options.append;
        if (append) {
            if (state.loading || state.loadingMore || !state.hasMore) {
                return null;
            }
        } else if (state.loading) {
            return null;
        }

        const filters = currentFilters();
        const queryKey = buildQueryKey(filters);
        const page = append ? state.page + 1 : 1;
        const requestSeq = ++state.requestSeq;

        if (!append) {
            state.pageSize = filters.pageSize;
        }
        if (append) {
            state.loadingMore = true;
        } else {
            state.loading = true;
            if (state.queryKey !== queryKey) {
                state.selectedUid = "";
                state.detail = null;
                renderDetail(null);
            }
        }
        renderLoadMore();

        const params = new URLSearchParams();
        if (filters.query) params.set("q", filters.query);
        if (filters.queryMode) params.set("query_mode", filters.queryMode);
        if (filters.keywordQuery)
            params.set("keyword_query", filters.keywordQuery);
        if (filters.semanticQuery) {
            params.set("semantic_query", filters.semanticQuery);
        }
        if (filters.enabled !== null)
            params.set("enabled", String(filters.enabled));
        if (filters.animated !== null) {
            params.set("animated", String(filters.animated));
        }
        if (filters.pinned !== null)
            params.set("pinned", String(filters.pinned));
        if (filters.sort) params.set("sort", filters.sort);
        params.set("top_k", String(filters.topK));
        params.set("page", String(page));
        params.set("page_size", String(filters.pageSize));

        try {
            const response = await api(
                `/api/v1/management/memes?${params.toString()}`,
            );
            if (!response.ok) throw new Error(await response.text());
            const payload = await response.json();
            if (requestSeq !== state.requestSeq) return payload;

            const nextItems = Array.isArray(payload?.items)
                ? payload.items
                : [];
            state.queryKey = queryKey;
            state.queryMeta = {
                queryMode: String(payload?.query_mode || ""),
                keywordQuery: String(payload?.keyword_query || ""),
                semanticQuery: String(payload?.semantic_query || ""),
                sort: String(payload?.sort || filters.sort || "updated_at"),
            };
            state.page = Number(payload?.page || page);
            state.pageSize = Number(payload?.page_size || filters.pageSize);
            state.total = Number(payload?.total || 0);
            state.hasMore = Boolean(
                payload?.has_more ?? state.page * state.pageSize < state.total,
            );
            state.listItems = append
                ? state.listItems.concat(nextItems)
                : nextItems;
            if (
                state.selectedUid &&
                !state.listItems.some((item) => item.uid === state.selectedUid)
            ) {
                state.selectedUid = "";
                state.detail = null;
                renderDetail(null);
            }
            renderList();
            return payload;
        } finally {
            if (requestSeq === state.requestSeq) {
                if (append) {
                    state.loadingMore = false;
                } else {
                    state.loading = false;
                }
                renderLoadMore();
            }
        }
    }

    async function refreshAll() {
        if (state.loading) return;
        try {
            await Promise.all([fetchStats(), fetchList()]);
            if (state.selectedUid) {
                await loadDetail(state.selectedUid, { silent: true });
            }
            state.loaded = true;
        } catch (error) {
            showError(error);
        }
    }

    async function loadDetail(uid, options = {}) {
        const targetUid = String(uid || "").trim();
        if (!targetUid) return;
        const response = await api(
            `/api/v1/management/memes/${encodeURIComponent(targetUid)}`,
        );
        if (!response.ok) throw new Error(await response.text());
        const payload = await response.json();
        state.selectedUid = targetUid;
        renderDetail(payload);
        if (!options.silent) {
            renderList();
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
        await Promise.all([
            loadDetail(record.uid, { silent: true }),
            fetchStats(),
            fetchList(),
        ]);
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
        await Promise.all([fetchStats(), fetchList()]);
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

    function bindListReload(id, eventName = "change") {
        const el = get(id);
        if (!el) return;
        el.addEventListener(eventName, () => {
            fetchList().catch(showError);
        });
    }

    function maybeLoadMoreOnScroll() {
        const windowEl = get("memesListWindow");
        if (!windowEl || state.loading || state.loadingMore || !state.hasMore) {
            return;
        }
        const threshold = 96;
        if (
            windowEl.scrollTop + windowEl.clientHeight >=
            windowEl.scrollHeight - threshold
        ) {
            fetchList({ append: true }).catch(showError);
        }
    }

    const controller = {
        init() {
            if (state.initialized) return;
            state.initialized = true;
            get("btnMemesRefresh")?.addEventListener("click", refreshAll);
            get("btnMemesSearch")?.addEventListener("click", () => {
                fetchList().catch(showError);
            });
            get("btnMemesLoadMore")?.addEventListener("click", () => {
                fetchList({ append: true }).catch(showError);
            });
            get("memesListWindow")?.addEventListener(
                "scroll",
                maybeLoadMoreOnScroll,
            );
            get("btnMemesSave")?.addEventListener("click", () => {
                saveDetail().catch(showError);
            });
            get("btnMemesReanalyze")?.addEventListener("click", () => {
                queueAction("reanalyze").catch(showError);
            });
            get("btnMemesReindex")?.addEventListener("click", () => {
                queueAction("reindex").catch(showError);
            });
            get("btnMemesDelete")?.addEventListener("click", () => {
                deleteSelected().catch(showError);
            });
            bindEnter("memesSearchInput", () => {
                fetchList().catch(showError);
            });
            bindEnter("memesKeywordQuery", () => {
                fetchList().catch(showError);
            });
            bindEnter("memesSemanticQuery", () => {
                fetchList().catch(showError);
            });
            [
                "memesQueryMode",
                "memesEnabledFilter",
                "memesAnimatedFilter",
                "memesPinnedFilter",
                "memesSortSelect",
                "memesTopK",
                "memesPageSize",
            ].forEach((id) => bindListReload(id));
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
