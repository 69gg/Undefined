(function () {
    const G = window.WorkflowGraph;
    const scheduleState = {
        initialized: false,
        loaded: false,
        busy: false,
        editing: false,
        dirty: false,
        draftNew: true,
        selectedId: "",
        search: "",
        tasks: [],
        catalog: {
            presets: [],
            tools: [],
            agents: [],
            toolsets: [],
            node_type_meta: [],
        },
        graph: null,
        canvas: null,
        inspector: null,
        savedSnapshot: "",
        issues: [],
        page: "list",
        editorInView: false,
    };

    function i18nFormat(key, params) {
        let text = t(key);
        Object.keys(params || {}).forEach((name) => {
            text = text.replaceAll(`{${name}}`, String(params[name]));
        });
        return text;
    }

    async function parseJsonSafe(response) {
        try {
            return await response.json();
        } catch (_error) {
            return null;
        }
    }

    function requestError(response, payload) {
        const fallback =
            `${response.status} ${response.statusText || "Request failed"}`.trim();
        if (!payload || typeof payload !== "object") return fallback;
        const base = payload.error ? String(payload.error) : fallback;
        return payload.detail ? `${base}: ${payload.detail}` : base;
    }

    function kindOf(task) {
        const start =
            (task.nodes || []).find((node) => node && node.id === "start") ||
            {};
        return String(start.kind || task.start_kind || "").trim();
    }

    function taskTitle(task) {
        return (
            String(task.task_name || "").trim() ||
            String(task.task_id || "").trim() ||
            t("schedules.untitled")
        );
    }

    function formatDateTime(value) {
        const text = String(value || "").trim();
        if (!text) return "--";
        const date = new Date(text);
        if (Number.isNaN(date.getTime())) return text;
        return date.toLocaleString();
    }

    function setPageStatus(message) {
        const status = get("scheduleStatus");
        if (status) status.textContent = message || "";
    }

    function setEditorStatus(message, type) {
        const status = get("wfEditorStatus");
        if (!status) return;
        status.textContent = message || "";
        status.className = `status-msg ${type || ""}`.trim();
    }

    function setBusy(loading) {
        scheduleState.busy = loading;
        ["btnSchedulesRefresh", "btnSchedulesNew", "btnWfSave"].forEach(
            (id) => {
                const button = get(id);
                if (button) button.disabled = loading;
            },
        );
    }

    function snapshotOf(task) {
        const copy = G.clone(task || {});
        return JSON.stringify({
            task_name: copy.task_name,
            enabled: copy.enabled,
            consume_ai_loop: copy.consume_ai_loop,
            auto_send_final: copy.auto_send_final,
            address: copy.address,
            max_executions: copy.max_executions,
            cooldown_seconds: copy.cooldown_seconds,
            nodes: copy.nodes,
            edges: copy.edges,
            ui: copy.ui,
        });
    }

    function markDirty() {
        if (!scheduleState.graph) return;
        scheduleState.dirty =
            snapshotOf(scheduleState.graph.payload()) !==
            scheduleState.savedSnapshot;
        get("tab-schedules")?.classList.toggle("is-dirty", scheduleState.dirty);
    }

    function confirmLeave() {
        if (!scheduleState.editing || !scheduleState.dirty) return true;
        return window.confirm(t("schedules.confirm_leave"));
    }

    function paletteGroups() {
        const meta = scheduleState.catalog.node_type_meta || [];
        const byId = {};
        meta.forEach((item) => {
            byId[item.id] = item;
        });
        const groups = { action: [], llm: [], branch: [], loop: [] };
        G.PALETTE_TYPES.forEach((item) => {
            if (!groups[item.group]) groups[item.group] = [];
            groups[item.group].push({
                ...item,
                label: t(`schedules.node_type.${item.id}`) || item.id,
            });
        });
        return groups;
    }

    function renderPalette() {
        const box = get("wfPalette");
        if (!box) return;
        const groups = paletteGroups();
        box.innerHTML = Object.keys(groups)
            .map((group) => {
                const items = groups[group];
                if (!items.length) return "";
                return `<div class="wf-palette-group">
                    <div class="wf-palette-label">${escapeHtml(t(`schedules.group_${group}`))}</div>
                    ${items
                        .map(
                            (item) => `
                        <button type="button" class="wf-palette-item" draggable="true" data-node-type="${escapeHtml(item.id)}">
                            <span class="wf-palette-swatch" style="--wf-swatch:${WorkflowCanvas.SWATCH[item.id] || "#d97757"}"></span>
                            ${escapeHtml(item.label)}
                        </button>`,
                        )
                        .join("")}
                </div>`;
            })
            .join("");
        box.querySelectorAll("[data-node-type]").forEach((button) => {
            button.addEventListener("dragstart", (event) => {
                event.dataTransfer.setData(
                    "application/x-undefined-node",
                    button.getAttribute("data-node-type") || "",
                );
            });
            button.addEventListener("click", () => {
                if (!scheduleState.graph) return;
                const { selectedId } = scheduleState.graph.getState();
                scheduleState.graph.addNode(
                    button.getAttribute("data-node-type"),
                    null,
                    selectedId ? { from: selectedId } : { from: "start" },
                );
            });
        });
    }

    function renderList() {
        const list = get("scheduleList");
        if (!list) return;
        const search = scheduleState.search.trim().toLowerCase();
        const items = scheduleState.tasks.filter((task) => {
            if (!search) return true;
            const blob = [
                task.task_id,
                task.task_name,
                kindOf(task),
                JSON.stringify(task.channels || []),
                task.last_status,
            ]
                .join(" ")
                .toLowerCase();
            return blob.includes(search);
        });
        if (!items.length) {
            list.innerHTML = `<div class="muted-sm">${escapeHtml(
                search ? t("schedules.no_results") : t("schedules.empty"),
            )}</div>`;
            return;
        }
        list.innerHTML = items
            .map((task) => {
                const kind = kindOf(task);
                const failed = task.last_status === "failed";
                const selected =
                    scheduleState.editing &&
                    !scheduleState.draftNew &&
                    scheduleState.selectedId === task.task_id;
                const cardClass = [
                    "schedule-flow-card",
                    failed ? "is-failed" : "",
                    selected ? "is-selected" : "",
                ]
                    .filter(Boolean)
                    .join(" ");
                return `
                <button type="button" class="${cardClass}" data-task-id="${escapeHtml(task.task_id)}">
                    <div class="schedule-flow-title">${escapeHtml(taskTitle(task))}</div>
                    <div class="schedule-flow-meta">
                        <span class="schedule-flow-kind">${escapeHtml(kind || "--")}</span>
                        <span>${escapeHtml(task.enabled === false ? t("schedules.disabled") : t("schedules.enabled"))}</span>
                        <span>${escapeHtml(task.last_status || "--")}</span>
                        <span>${escapeHtml(t("schedules.next_run"))}: ${escapeHtml(formatDateTime(task.next_run_time))}</span>
                    </div>
                </button>`;
            })
            .join("");
        list.querySelectorAll("[data-task-id]").forEach((button) => {
            button.addEventListener("click", () =>
                openEditor(button.getAttribute("data-task-id")),
            );
        });
    }

    function renderStats() {
        const tasks = scheduleState.tasks;
        const eventKinds = G.EVENT_KINDS;
        get("scheduleStatTotal").textContent = String(tasks.length);
        get("scheduleStatEvent").textContent = String(
            tasks.filter((task) => eventKinds.has(kindOf(task))).length,
        );
        get("scheduleStatTime").textContent = String(
            tasks.filter((task) => !eventKinds.has(kindOf(task))).length,
        );
        get("scheduleStatFailed").textContent = String(
            tasks.filter((task) => task.last_status === "failed").length,
        );
    }

    function renderPresets() {
        const grid = get("schedulePresetGrid");
        if (!grid) return;
        const presets = [
            { id: "", name: t("schedules.preset_blank"), task: G.emptyTask() },
            ...(scheduleState.catalog.presets || []),
        ];
        grid.innerHTML = presets
            .map(
                (preset) => `
            <button type="button" class="wf-preset-card" data-preset-id="${escapeHtml(preset.id)}">
                <strong>${escapeHtml(preset.name)}</strong>
            </button>`,
            )
            .join("");
        grid.querySelectorAll("[data-preset-id]").forEach((button) => {
            button.addEventListener("click", () => {
                const id = button.getAttribute("data-preset-id") || "";
                const preset = presets.find((item) => item.id === id);
                hidePresetDialog();
                openDraft(preset?.task || G.emptyTask());
            });
        });
    }

    function showPresetDialog() {
        renderPresets();
        const dialog = get("schedulePresetDialog");
        if (dialog) dialog.hidden = false;
    }

    function hidePresetDialog() {
        const dialog = get("schedulePresetDialog");
        if (dialog) dialog.hidden = true;
    }

    function syncEditorChrome() {
        const { task } = scheduleState.graph.getState();
        const nameInput = get("wfTaskName");
        const idInput = get("wfTaskId");
        const enabled = get("wfEnabled");
        if (nameInput && document.activeElement !== nameInput) {
            nameInput.value = task.task_name || "";
        }
        if (idInput) {
            idInput.value = scheduleState.draftNew
                ? idInput.value
                : scheduleState.selectedId;
            idInput.disabled =
                !scheduleState.editing || !scheduleState.draftNew;
        }
        if (enabled) enabled.checked = task.enabled !== false;
        get("btnWfDelete").disabled =
            !scheduleState.editing || scheduleState.draftNew;
        const json = get("wfGraphJson");
        if (json && document.activeElement !== json) {
            json.value = G.prettyJson(scheduleState.graph.payload());
        }
        const badge = get("wfIssueBadge");
        if (badge) {
            if (scheduleState.issues.length) {
                badge.textContent = i18nFormat("schedules.issue_count", {
                    count: scheduleState.issues.length,
                });
                badge.className = "wf-issue-badge is-error";
            } else {
                badge.textContent = t("schedules.validate_ok");
                badge.className = "wf-issue-badge is-ok";
            }
        }
        renderMobileNodes(task);
        markDirty();
    }

    function renderMobileNodes(task) {
        const box = get("wfMobileNodes");
        if (!box) return;
        box.innerHTML = (task.nodes || [])
            .map(
                (node) => `
            <button type="button" class="schedule-flow-card" data-select-node="${escapeHtml(node.id)}">
                <div class="schedule-flow-title">${escapeHtml(node.id)}</div>
                <div class="muted-sm">${escapeHtml(t(`schedules.node_type.${node.type}`) || node.type)}</div>
            </button>`,
            )
            .join("");
        box.querySelectorAll("[data-select-node]").forEach((button) => {
            button.addEventListener("click", () =>
                scheduleState.graph.selectNode(
                    button.getAttribute("data-select-node"),
                ),
            );
        });
    }

    function ensureGraph(task) {
        if (!scheduleState.graph) {
            scheduleState.graph = G.createGraph(task);
            scheduleState.graph.subscribe(() => {
                if (scheduleState.editing) syncEditorChrome();
            });
            scheduleState.canvas = window.WorkflowCanvas.createCanvas(
                get("wfCanvas"),
                scheduleState.graph,
            );
            scheduleState.inspector = window.WorkflowInspector.createInspector(
                get("wfInspector"),
                scheduleState.graph,
                () => scheduleState.catalog,
            );
        } else {
            scheduleState.graph.load(task);
            scheduleState.inspector?.render();
            scheduleState.canvas?.render();
        }
        renderPalette();
    }

    function scroller() {
        return get("schedulePages") || get("tab-schedules");
    }

    function prefersReducedMotion() {
        return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }

    function showSchedulePage(page) {
        const target =
            page === "editor"
                ? get("scheduleEditorView")
                : get("scheduleListView");
        const box = scroller();
        if (!target || !box) return;
        scheduleState.page = page;
        const top =
            target.getBoundingClientRect().top -
            box.getBoundingClientRect().top +
            box.scrollTop;
        box.scrollTo({
            top,
            behavior: prefersReducedMotion() ? "auto" : "smooth",
        });
        if (page === "editor") scheduleState.canvas?.render();
    }

    function restoreSchedulePage() {
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() =>
                showSchedulePage(scheduleState.page || "list"),
            );
        });
    }

    function syncEmptyState() {
        const empty = get("wfEmptyState");
        const editor = get("scheduleEditorView");
        if (empty) empty.hidden = scheduleState.editing;
        editor?.classList.toggle("is-empty", !scheduleState.editing);
        get("tab-schedules")?.classList.toggle(
            "is-editing",
            scheduleState.editing,
        );
        [
            "btnWfSave",
            "btnWfLayout",
            "wfTaskName",
            "wfEnabled",
            "wfTaskId",
        ].forEach((id) => {
            const node = get(id);
            if (!node) return;
            if (id === "wfTaskId") {
                node.disabled =
                    !scheduleState.editing || !scheduleState.draftNew;
                return;
            }
            node.disabled = !scheduleState.editing;
        });
        const del = get("btnWfDelete");
        if (del) {
            del.disabled = !scheduleState.editing || scheduleState.draftNew;
        }
    }

    function setEditing(editing) {
        scheduleState.editing = editing;
        if (!editing) scheduleState.page = "list";
        syncEmptyState();
        if (typeof syncMainContentLayout === "function")
            syncMainContentLayout();
    }

    function openDraft(task) {
        if (!confirmLeave()) return;
        scheduleState.draftNew = true;
        scheduleState.selectedId = "";
        scheduleState.issues = [];
        ensureGraph({ ...G.emptyTask(), ...task });
        scheduleState.savedSnapshot = snapshotOf(scheduleState.graph.payload());
        scheduleState.dirty = false;
        const idInput = get("wfTaskId");
        if (idInput) idInput.value = "";
        setEditing(true);
        setEditorStatus("");
        syncEditorChrome();
        writeTaskQuery("new");
        renderList();
        window.requestAnimationFrame(() =>
            window.requestAnimationFrame(() => showSchedulePage("editor")),
        );
    }

    function openEditor(taskId) {
        const sameOpen =
            scheduleState.editing &&
            !scheduleState.draftNew &&
            scheduleState.selectedId === taskId;
        if (sameOpen) {
            showSchedulePage("editor");
            return;
        }
        const task = scheduleState.tasks.find(
            (item) => item.task_id === taskId,
        );
        if (!task) return;
        if (!confirmLeave()) return;
        scheduleState.draftNew = false;
        scheduleState.selectedId = taskId;
        scheduleState.issues = [];
        ensureGraph(task);
        scheduleState.savedSnapshot = snapshotOf(scheduleState.graph.payload());
        scheduleState.dirty = false;
        setEditing(true);
        setEditorStatus("");
        syncEditorChrome();
        writeTaskQuery(taskId);
        renderList();
        window.requestAnimationFrame(() =>
            window.requestAnimationFrame(() => showSchedulePage("editor")),
        );
        validateDraft();
    }

    function closeEditor() {
        if (!confirmLeave()) return;
        setEditing(false);
        scheduleState.dirty = false;
        writeTaskQuery("");
        renderList();
        showSchedulePage("list");
    }

    function writeTaskQuery(taskId) {
        const url = new URL(window.location.href);
        if (state.tab === "schedules" && taskId)
            url.searchParams.set("task", taskId);
        else url.searchParams.delete("task");
        window.history.replaceState(null, "", url);
    }

    async function validateDraft() {
        if (!scheduleState.graph) return;
        try {
            const response = await api("/api/runtime/automations/validate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(scheduleState.graph.payload()),
            });
            const body = await parseJsonSafe(response);
            scheduleState.issues = Array.isArray(body?.issues)
                ? body.issues
                : [];
            syncEditorChrome();
        } catch (_error) {
            scheduleState.issues = [];
        }
    }

    async function refresh(options = {}) {
        const force = Boolean(options.force);
        if (scheduleState.busy && !force) return;
        const managedBusy = !scheduleState.busy;
        if (managedBusy) setBusy(true);
        try {
            const [listResp, catalogResp] = await Promise.all([
                api("/api/runtime/automations", {
                    signal: getAbortSignal("schedules"),
                }),
                api("/api/runtime/automations/catalog"),
            ]);
            const payload = await parseJsonSafe(listResp);
            if (!listResp.ok) throw new Error(requestError(listResp, payload));
            scheduleState.tasks = Array.isArray(payload.items)
                ? payload.items
                : [];
            if (catalogResp.ok) {
                scheduleState.catalog = (await parseJsonSafe(catalogResp)) || {
                    presets: [],
                    tools: [],
                    agents: [],
                    toolsets: [],
                };
            }
            renderStats();
            renderList();
            scheduleState.loaded = true;
            setPageStatus(
                i18nFormat("schedules.loaded", {
                    count: scheduleState.tasks.length,
                }),
            );
            if (!options.skipOpenFromQuery) maybeOpenFromQuery();
        } catch (error) {
            if (error.name === "AbortError") return;
            setPageStatus(
                `${t("schedules.save_failed")}: ${error.message || error}`,
            );
        } finally {
            if (managedBusy) setBusy(false);
        }
    }

    function maybeOpenFromQuery() {
        if (scheduleState.editing) return;
        const params = new URLSearchParams(window.location.search);
        const taskId = params.get("task") || state.initialTask || "";
        if (!taskId) return;
        if (taskId === "new") {
            showPresetDialog();
            return;
        }
        if (scheduleState.tasks.some((item) => item.task_id === taskId)) {
            openEditor(taskId);
        }
    }

    async function save() {
        if (!scheduleState.graph || scheduleState.busy) return;
        try {
            const payload = scheduleState.graph.payload();
            const taskId = scheduleState.draftNew
                ? String(get("wfTaskId").value || "").trim()
                : scheduleState.selectedId;
            if (scheduleState.draftNew && taskId) payload.task_id = taskId;
            setBusy(true);
            const response = await api(
                scheduleState.draftNew
                    ? "/api/runtime/automations"
                    : `/api/runtime/automations/${encodeURIComponent(scheduleState.selectedId)}`,
                {
                    method: scheduleState.draftNew ? "POST" : "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                },
            );
            const body = await parseJsonSafe(response);
            if (!response.ok) throw new Error(requestError(response, body));
            setEditorStatus(t("schedules.saved"), "success");
            showToast(t("schedules.saved"), "success");
            scheduleState.draftNew = false;
            scheduleState.selectedId = body.task?.task_id || taskId;
            if (body.task) {
                ensureGraph(body.task);
                scheduleState.savedSnapshot = snapshotOf(
                    scheduleState.graph.payload(),
                );
            }
            scheduleState.dirty = false;
            writeTaskQuery(scheduleState.selectedId);
            await refresh({ force: true, skipOpenFromQuery: true });
            window.requestAnimationFrame(() =>
                window.requestAnimationFrame(() => showSchedulePage("list")),
            );
        } catch (error) {
            setEditorStatus(
                `${t("schedules.save_failed")}: ${error.message || error}`,
                "error",
            );
            validateDraft();
        } finally {
            setBusy(false);
        }
    }

    async function removeSelected() {
        if (scheduleState.draftNew || !scheduleState.selectedId) return;
        if (!confirm(t("schedules.confirm_delete"))) return;
        setBusy(true);
        try {
            const response = await api(
                `/api/runtime/automations/${encodeURIComponent(scheduleState.selectedId)}`,
                { method: "DELETE" },
            );
            const body = await parseJsonSafe(response);
            if (!response.ok) throw new Error(requestError(response, body));
            showToast(t("schedules.deleted"), "success");
            scheduleState.dirty = false;
            closeEditor();
            await refresh({ force: true, skipOpenFromQuery: true });
        } catch (error) {
            showToast(
                `${t("runtime.failed")}: ${error.message || error}`,
                "error",
                5000,
            );
        } finally {
            setBusy(false);
        }
    }

    function bindEditorKeys(event) {
        if (!scheduleState.editing) return;
        const typing =
            event.target &&
            (event.target.tagName === "INPUT" ||
                event.target.tagName === "TEXTAREA" ||
                event.target.tagName === "SELECT");
        if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "s"
        ) {
            event.preventDefault();
            save();
            return;
        }
        if (!scheduleState.editorInView) return;
        if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "z"
        ) {
            event.preventDefault();
            if (event.shiftKey) scheduleState.graph?.redo();
            else scheduleState.graph?.undo();
            return;
        }
        if (
            (event.ctrlKey || event.metaKey) &&
            event.key.toLowerCase() === "y"
        ) {
            event.preventDefault();
            scheduleState.graph?.redo();
            return;
        }
        if (typing) return;
        if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault();
            scheduleState.graph?.removeSelected();
        }
        if (event.key === "Escape") {
            scheduleState.graph?.selectNode("");
        }
    }

    function bindPageObserver() {
        const box = scroller();
        const editor = get("scheduleEditorView");
        if (!box || !editor) return;
        const observer = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    if (entry.target !== editor) return;
                    scheduleState.editorInView =
                        entry.isIntersecting && entry.intersectionRatio >= 0.4;
                    if (scheduleState.editorInView)
                        scheduleState.page = "editor";
                    else if (entry.intersectionRatio < 0.15)
                        scheduleState.page = "list";
                });
            },
            { root: box, threshold: [0.15, 0.4, 0.6] },
        );
        observer.observe(editor);
    }

    function bindListWheel() {
        const list = get("scheduleList");
        if (!list) return;
        list.addEventListener(
            "wheel",
            (event) => {
                const box = scroller();
                if (!box) return;
                const atBottom =
                    list.scrollTop + list.clientHeight >= list.scrollHeight - 1;
                const atTop = list.scrollTop <= 0;
                if (event.deltaY > 0 && atBottom) {
                    event.preventDefault();
                    box.scrollBy({ top: event.deltaY });
                } else if (event.deltaY < 0 && atTop) {
                    event.preventDefault();
                    box.scrollBy({ top: event.deltaY });
                }
            },
            { passive: false },
        );
    }

    function bindEvents() {
        get("btnSchedulesRefresh")?.addEventListener("click", refresh);
        get("btnSchedulesNew")?.addEventListener("click", showPresetDialog);
        get("btnPresetClose")?.addEventListener("click", hidePresetDialog);
        get("schedulePresetDialog")?.addEventListener("click", (event) => {
            if (event.target.id === "schedulePresetDialog") hidePresetDialog();
        });
        get("scheduleSearchInput")?.addEventListener("input", (event) => {
            scheduleState.search = String(event.target.value || "");
            renderList();
        });
        get("btnWfBack")?.addEventListener("click", () =>
            showSchedulePage("list"),
        );
        get("btnWfEmptyBack")?.addEventListener("click", () =>
            showSchedulePage("list"),
        );
        get("btnWfScrollEditor")?.addEventListener("click", () =>
            showSchedulePage("editor"),
        );
        get("btnWfSave")?.addEventListener("click", save);
        get("btnWfDelete")?.addEventListener("click", removeSelected);
        get("btnWfLayout")?.addEventListener("click", () =>
            scheduleState.graph?.autoLayout(),
        );
        get("wfTaskName")?.addEventListener("change", (event) => {
            scheduleState.graph?.setMeta({ task_name: event.target.value });
        });
        get("wfEnabled")?.addEventListener("change", (event) => {
            scheduleState.graph?.setMeta({ enabled: event.target.checked });
        });
        get("btnWfApplyJson")?.addEventListener("click", () => {
            try {
                const parsed = JSON.parse(get("wfGraphJson").value || "{}");
                if (!parsed || !Array.isArray(parsed.nodes)) {
                    throw new Error(t("schedules.graph_json"));
                }
                scheduleState.graph.load(parsed);
            } catch (error) {
                setEditorStatus(String(error.message || error), "error");
            }
        });
        document.addEventListener("keydown", bindEditorKeys);
        bindPageObserver();
        bindListWheel();
        syncEmptyState();
    }

    const controller = {
        init() {
            if (scheduleState.initialized) return;
            scheduleState.initialized = true;
            bindEvents();
        },
        onTabActivated(tab) {
            if (tab !== "schedules") return;
            if (typeof state !== "undefined" && !state.authenticated) return;
            if (!scheduleState.loaded) refresh();
            if (typeof syncMainContentLayout === "function")
                syncMainContentLayout();
            restoreSchedulePage();
        },
        confirmLeave,
        isEditing() {
            return scheduleState.editing;
        },
        onLanguageChanged() {
            if (!scheduleState.loaded) return;
            renderStats();
            renderList();
            if (scheduleState.editing) {
                renderPalette();
                scheduleState.inspector?.render();
                syncEditorChrome();
            }
        },
        refresh,
    };

    window.SchedulesController = controller;
})();
