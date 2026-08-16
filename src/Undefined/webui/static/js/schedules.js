(function () {
    const EVENT_KINDS = new Set([
        "message",
        "poke",
        "member_join",
        "member_leave",
    ]);
    const TIME_KINDS = new Set(["cron", "daily", "at", "interval"]);

    const scheduleState = {
        initialized: false,
        loaded: false,
        busy: false,
        tasks: [],
        catalog: { presets: [] },
        selectedId: "",
        draftNew: true,
        search: "",
        lastFocused: null,
    };

    function i18nFormat(key, params = {}) {
        let text = t(key);
        Object.keys(params).forEach((name) => {
            text = text.replaceAll(`{${name}}`, String(params[name]));
        });
        return text;
    }

    function parseJsonText(value, fallback, label) {
        const text = String(value || "").trim();
        if (!text) return fallback;
        try {
            return JSON.parse(text);
        } catch (error) {
            throw new Error(`${label}: ${error.message || error}`);
        }
    }

    function prettyJson(value) {
        return JSON.stringify(value === undefined ? null : value, null, 2);
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

    function csvInts(value) {
        return String(value || "")
            .split(/[,，\s]+/)
            .map((item) => item.trim())
            .filter(Boolean)
            .map((item) => Number(item))
            .filter((item) => Number.isInteger(item));
    }

    function startNode(task) {
        const nodes = Array.isArray(task.nodes) ? task.nodes : [];
        return (
            nodes.find((node) => node && node.id === "start") || {
                id: "start",
                type: "start",
                kind: "message",
                channels: ["group"],
            }
        );
    }

    function emptyTask() {
        return {
            task_name: "",
            enabled: true,
            consume_ai_loop: true,
            auto_send_final: true,
            nodes: [
                {
                    id: "start",
                    type: "start",
                    kind: "message",
                    channels: ["group"],
                    mentions: [],
                    text: "",
                    pass_text: "stripped",
                    text_match: "contains",
                },
            ],
            edges: [],
        };
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

    function setStatus(message, type = "") {
        const status = get("scheduleEditorStatus");
        if (!status) return;
        status.textContent = message || "";
        status.className = `status-msg ${type}`.trim();
    }

    function setPageStatus(message) {
        const status = get("scheduleStatus");
        if (status) status.textContent = message || "";
    }

    function setBusy(loading) {
        scheduleState.busy = loading;
        ["btnSchedulesRefresh", "btnSchedulesNew", "btnScheduleSave"].forEach(
            (id) => {
                const button = get(id);
                if (button) button.disabled = loading;
            },
        );
    }

    function kindOf(task) {
        return String(startNode(task).kind || task.start_kind || "").trim();
    }

    function defaultNode(type) {
        const id = `${type.replace(/[^a-z]/g, "_")}_${Math.random().toString(16).slice(2, 6)}`;
        if (type === "tool") {
            return { id, type, tool_name: "", args: {}, emit: false };
        }
        if (type === "template") {
            return { id, type, template: "{{trigger.text}}", emit: true };
        }
        if (type === "llm.blank") {
            return {
                id,
                type,
                system_prompt: "",
                user_prompt: "{{trigger.text}}",
                tools: [],
                emit: false,
            };
        }
        if (type === "llm.agent") {
            return {
                id,
                type,
                agent: "",
                input: "{{trigger.text}}",
                emit: false,
            };
        }
        if (type === "llm.main") {
            return { id, type, prompt: "{{trigger.text}}", emit: true };
        }
        if (type === "branch.if") {
            return {
                id,
                type,
                input: "{{trigger.text_original}}",
                cases: [{ id: "hit", text: "" }],
            };
        }
        if (type === "branch.llm") {
            return {
                id,
                type,
                input: "{{trigger.text}}",
                options: [
                    { id: "a", description: "选项 A" },
                    { id: "b", description: "选项 B" },
                ],
            };
        }
        if (type === "loop.times") {
            return { id, type, count: 3, body: [] };
        }
        return { id, type, source: "{{web}}", body: [] };
    }

    function nodeFields(node) {
        const type = String(node.type || "");
        if (type === "tool") {
            return prettyJson({
                tool_name: node.tool_name || "",
                args: node.args || node.tool_args || {},
                emit: Boolean(node.emit),
            });
        }
        if (type === "template") {
            return prettyJson({
                template: node.template || "",
                emit: Boolean(node.emit),
            });
        }
        if (type === "llm.blank") {
            return prettyJson({
                system_prompt: node.system_prompt || "",
                user_prompt: node.user_prompt || "",
                tools: node.tools || [],
                toolsets: node.toolsets || [],
                agents: node.agents || [],
                emit: Boolean(node.emit),
            });
        }
        if (type === "llm.agent") {
            return prettyJson({
                agent: node.agent || "",
                input: node.input || "",
                emit: Boolean(node.emit),
            });
        }
        if (type === "llm.main") {
            return prettyJson({
                prompt: node.prompt || "",
                emit: Boolean(node.emit),
            });
        }
        if (type === "branch.if") {
            return prettyJson({
                input: node.input || "{{trigger.text_original}}",
                cases: node.cases || [],
            });
        }
        if (type === "branch.llm") {
            return prettyJson({
                input: node.input || "",
                options: node.options || [],
            });
        }
        if (type === "loop.times") {
            return prettyJson({
                count: node.count || 25,
                body: node.body || [],
                until: node.until || null,
            });
        }
        if (type === "loop.each") {
            return prettyJson({
                source: node.source || "",
                body: node.body || [],
            });
        }
        return prettyJson(node);
    }

    function renderMentions(mentions) {
        const box = get("scheduleMentions");
        if (!box) return;
        const items = Array.isArray(mentions) ? mentions : [];
        box.innerHTML = items
            .map(
                (value, index) => `
            <div class="schedule-mention-row" data-mention-index="${index}">
                <input class="form-control" data-mention-input="1" value="${escapeHtml(value)}" placeholder="10001 or *" />
                <button type="button" class="btn ghost" data-mention-any="1">${escapeHtml(t("schedules.mention_any"))}</button>
                <button type="button" class="btn ghost" data-mention-remove="1">×</button>
            </div>`,
            )
            .join("");
    }

    function readMentions() {
        return Array.from(
            document.querySelectorAll("#scheduleMentions [data-mention-input]"),
        )
            .map((input) => String(input.value || "").trim())
            .filter(Boolean);
    }

    function renderNodes(nodes) {
        const box = get("scheduleNodes");
        if (!box) return;
        const list = (Array.isArray(nodes) ? nodes : []).filter(
            (node) => node && node.id !== "start",
        );
        box.innerHTML = list
            .map(
                (node) => `
            <div class="schedule-node-card" data-node-id="${escapeHtml(node.id)}">
                <div class="schedule-node-head">
                    <strong>${escapeHtml(node.type || "")}</strong>
                    <input class="form-control form-control-sm" data-node-id-input="1" value="${escapeHtml(node.id)}" />
                    <button type="button" class="btn ghost" data-node-remove="1">${escapeHtml(t("schedules.node_remove"))}</button>
                </div>
                <textarea class="form-control form-textarea schedule-json-area" data-node-json="1" spellcheck="false">${escapeHtml(nodeFields(node))}</textarea>
            </div>`,
            )
            .join("");
    }

    function readNodesFromCards(start) {
        const nodes = [start];
        document
            .querySelectorAll("#scheduleNodes .schedule-node-card")
            .forEach((card) => {
                const idInput = card.querySelector("[data-node-id-input]");
                const jsonArea = card.querySelector("[data-node-json]");
                const nodeId = String(
                    idInput?.value || card.getAttribute("data-node-id") || "",
                ).trim();
                let extra = {};
                try {
                    extra = parseJsonText(
                        jsonArea?.value,
                        {},
                        t("schedules.node_json"),
                    );
                } catch (_error) {
                    extra = {};
                }
                const type = String(
                    extra.type ||
                        card.querySelector("strong")?.textContent ||
                        "tool",
                );
                nodes.push({ ...extra, id: nodeId, type });
            });
        return nodes;
    }

    function fillEditor(task, draftNew) {
        const start = startNode(task);
        const kind = String(start.kind || "message");
        get("scheduleTaskId").value = draftNew
            ? ""
            : String(task.task_id || "");
        get("scheduleTaskId").disabled = !draftNew;
        get("scheduleTaskName").value = String(task.task_name || "");
        get("scheduleKind").value = kind;
        get("scheduleTargetAddress").value = String(task.address || "");
        get("scheduleMaxExecutions").value = task.max_executions || "";
        get("scheduleEnabled").checked = task.enabled !== false;
        get("scheduleConsume").checked = task.consume_ai_loop !== false;
        get("scheduleAutoSend").checked = task.auto_send_final !== false;
        const channels = new Set(start.channels || []);
        get("scheduleChGroup").checked = channels.has("group");
        get("scheduleChPrivate").checked = channels.has("private");
        get("scheduleChWechat").checked = channels.has("wechat");
        get("scheduleGroupIds").value = (start.group_ids || []).join(", ");
        get("scheduleUserIds").value = (start.user_ids || []).join(", ");
        renderMentions(start.mentions || []);
        get("scheduleText").value = String(start.text || "");
        get("scheduleTextMatch").value = String(start.text_match || "contains");
        get("schedulePassText").value = String(
            start.pass_text ||
                (start.mentions && start.mentions.length
                    ? "stripped"
                    : "original"),
        );
        const clock =
            start.clock && typeof start.clock === "object" ? start.clock : {};
        get("scheduleClockAfter").value = String(clock.after || "");
        get("scheduleClockBefore").value = String(clock.before || "");
        get("scheduleCron").value = String(start.cron || task.cron || "");
        get("scheduleDailyTime").value = String(start.time || "");
        get("scheduleAt").value = String(start.at || "");
        get("scheduleInterval").value = start.interval_seconds || "";
        renderNodes(task.nodes || []);
        get("scheduleEdgesJson").value = prettyJson(task.edges || []);
        const graph = {
            task_name: task.task_name || "",
            enabled: task.enabled !== false,
            consume_ai_loop: task.consume_ai_loop !== false,
            auto_send_final: task.auto_send_final !== false,
            address: task.address || "",
            nodes: task.nodes || [],
            edges: task.edges || [],
        };
        get("scheduleGraphJson").value = prettyJson(graph);
        const last = [
            t("schedules.last_run"),
            task.last_status || "--",
            formatDateTime(task.last_run_at),
            task.last_node_id ? `node=${task.last_node_id}` : "",
            task.last_error || "",
        ]
            .filter(Boolean)
            .join(" · ");
        get("scheduleLastRun").textContent = last;
        get("scheduleEditorModeLabel").textContent = draftNew
            ? t("schedules.editor_new")
            : t("schedules.editor_edit");
        get("scheduleEditorTaskId").textContent = draftNew
            ? t("schedules.draft")
            : String(task.task_id || "--");
        get("scheduleEditorBadge").textContent = kind || "--";
        toggleKindFields(kind);
        get("btnScheduleDelete").disabled = draftNew;
    }

    function toggleKindFields(kind) {
        const event = EVENT_KINDS.has(kind);
        get("scheduleChannelRow").style.display = event ? "flex" : "none";
        get("scheduleCronGroup").style.display = kind === "cron" ? "" : "none";
        get("scheduleDailyGroup").style.display =
            kind === "daily" ? "" : "none";
        get("scheduleAtGroup").style.display = kind === "at" ? "" : "none";
        get("scheduleIntervalGroup").style.display =
            kind === "interval" ? "" : "none";
    }

    function readEditor() {
        const kind = String(get("scheduleKind").value || "message");
        const channels = [];
        if (get("scheduleChGroup").checked) channels.push("group");
        if (get("scheduleChPrivate").checked) channels.push("private");
        if (get("scheduleChWechat").checked) channels.push("wechat");
        const mentions = readMentions();
        const clock = {};
        if (get("scheduleClockAfter").value.trim()) {
            clock.after = get("scheduleClockAfter").value.trim();
        }
        if (get("scheduleClockBefore").value.trim()) {
            clock.before = get("scheduleClockBefore").value.trim();
        }
        const start = {
            id: "start",
            type: "start",
            kind,
        };
        if (EVENT_KINDS.has(kind)) {
            start.channels = channels;
            const groupIds = csvInts(get("scheduleGroupIds").value);
            if (groupIds.length) start.group_ids = groupIds;
            const userIds = csvInts(get("scheduleUserIds").value);
            if (userIds.length) start.user_ids = userIds;
            if (mentions.length) start.mentions = mentions;
            if (get("scheduleText").value.trim()) {
                start.text = get("scheduleText").value.trim();
            }
            start.text_match = get("scheduleTextMatch").value;
            start.pass_text = get("schedulePassText").value;
        }
        if (Object.keys(clock).length) start.clock = clock;
        if (kind === "cron") start.cron = get("scheduleCron").value.trim();
        if (kind === "daily")
            start.time = get("scheduleDailyTime").value.trim();
        if (kind === "at") start.at = get("scheduleAt").value.trim();
        if (kind === "interval") {
            start.interval_seconds = Number(get("scheduleInterval").value || 0);
        }
        let edges = parseJsonText(
            get("scheduleEdgesJson").value,
            [],
            t("schedules.edges"),
        );
        if (!Array.isArray(edges)) edges = [];
        const nodes = readNodesFromCards(start);
        const payload = {
            task_name: get("scheduleTaskName").value.trim(),
            enabled: get("scheduleEnabled").checked,
            consume_ai_loop: get("scheduleConsume").checked,
            auto_send_final: get("scheduleAutoSend").checked,
            address: get("scheduleTargetAddress").value.trim() || null,
            nodes,
            edges,
        };
        const maxExec = String(get("scheduleMaxExecutions").value || "").trim();
        if (maxExec) payload.max_executions = Number(maxExec);
        const jsonOverride = String(
            get("scheduleGraphJson").value || "",
        ).trim();
        if (jsonOverride && jsonOverride !== "{}") {
            const parsed = parseJsonText(
                jsonOverride,
                null,
                t("schedules.graph_json"),
            );
            if (parsed && Array.isArray(parsed.nodes) && parsed.nodes.length) {
                return {
                    ...payload,
                    ...parsed,
                    nodes: parsed.nodes,
                    edges: parsed.edges || edges,
                };
            }
        }
        return payload;
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
                const selected =
                    !scheduleState.draftNew &&
                    task.task_id === scheduleState.selectedId;
                const kind = kindOf(task);
                return `
                <button type="button" class="schedule-list-item${selected ? " is-selected" : ""}" data-task-id="${escapeHtml(task.task_id)}">
                    <div class="schedule-list-main">
                        <div class="schedule-list-title">${escapeHtml(taskTitle(task))}</div>
                        <div class="schedule-list-sub"><code>${escapeHtml(kind)}</code> ${(task.channels || []).map(escapeHtml).join(" / ")}</div>
                    </div>
                    <div class="schedule-list-meta">
                        <span>${escapeHtml(task.enabled === false ? t("schedules.disabled") : t("schedules.enabled"))}</span>
                        <span>${escapeHtml(task.last_status || "--")}</span>
                    </div>
                </button>`;
            })
            .join("");
        list.querySelectorAll("[data-task-id]").forEach((button) => {
            button.addEventListener("click", () =>
                selectTask(button.getAttribute("data-task-id")),
            );
        });
    }

    function renderStats() {
        const tasks = scheduleState.tasks;
        get("scheduleStatTotal").textContent = String(tasks.length);
        get("scheduleStatEvent").textContent = String(
            tasks.filter((task) => EVENT_KINDS.has(kindOf(task))).length,
        );
        get("scheduleStatTime").textContent = String(
            tasks.filter((task) => TIME_KINDS.has(kindOf(task))).length,
        );
        get("scheduleStatFailed").textContent = String(
            tasks.filter((task) => task.last_status === "failed").length,
        );
    }

    function fillPresets() {
        const select = get("schedulePreset");
        if (!select) return;
        const presets = scheduleState.catalog.presets || [];
        select.innerHTML = `<option value="">${escapeHtml(t("schedules.preset_none"))}</option>${presets
            .map(
                (preset) =>
                    `<option value="${escapeHtml(preset.id)}">${escapeHtml(preset.name)}</option>`,
            )
            .join("")}`;
    }

    function newTask() {
        scheduleState.draftNew = true;
        scheduleState.selectedId = "";
        fillEditor(emptyTask(), true);
        renderList();
        setStatus("");
    }

    function selectTask(taskId) {
        const task = scheduleState.tasks.find(
            (item) => item.task_id === taskId,
        );
        if (!task) return;
        scheduleState.draftNew = false;
        scheduleState.selectedId = taskId;
        fillEditor(task, false);
        renderList();
        setStatus("");
    }

    async function refresh() {
        if (scheduleState.busy) return;
        setBusy(true);
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
                };
            }
            fillPresets();
            renderStats();
            renderList();
            if (!scheduleState.draftNew && scheduleState.selectedId) {
                const current = scheduleState.tasks.find(
                    (item) => item.task_id === scheduleState.selectedId,
                );
                if (current) fillEditor(current, false);
                else newTask();
            }
            scheduleState.loaded = true;
            setPageStatus(
                i18nFormat("schedules.loaded", {
                    count: scheduleState.tasks.length,
                }),
            );
        } catch (error) {
            if (error.name === "AbortError") return;
            setPageStatus(
                `${t("schedules.save_failed")}: ${error.message || error}`,
            );
        } finally {
            setBusy(false);
        }
    }

    async function save(event) {
        event.preventDefault();
        if (scheduleState.busy) return;
        try {
            const payload = readEditor();
            const taskId = scheduleState.draftNew
                ? String(get("scheduleTaskId").value || "").trim()
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
            setStatus(t("schedules.saved"), "success");
            showToast(t("schedules.saved"), "success");
            scheduleState.draftNew = false;
            scheduleState.selectedId = body.task?.task_id || taskId;
            await refresh();
        } catch (error) {
            setStatus(
                `${t("schedules.save_failed")}: ${error.message || error}`,
                "error",
            );
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
            newTask();
            await refresh();
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

    function applyPreset(presetId) {
        const preset = (scheduleState.catalog.presets || []).find(
            (item) => item.id === presetId,
        );
        if (!preset || !preset.task) return;
        fillEditor({ ...emptyTask(), ...preset.task }, true);
        scheduleState.draftNew = true;
        scheduleState.selectedId = "";
        renderList();
    }

    function bindEvents() {
        get("btnSchedulesRefresh")?.addEventListener("click", refresh);
        get("btnSchedulesNew")?.addEventListener("click", newTask);
        get("btnScheduleReset")?.addEventListener("click", () => {
            if (scheduleState.selectedId) selectTask(scheduleState.selectedId);
            else newTask();
        });
        get("btnScheduleDelete")?.addEventListener("click", removeSelected);
        get("scheduleEditor")?.addEventListener("submit", save);
        get("scheduleSearchInput")?.addEventListener("input", (event) => {
            scheduleState.search = String(event.target.value || "");
            renderList();
        });
        get("scheduleKind")?.addEventListener("change", (event) => {
            toggleKindFields(event.target.value);
        });
        get("schedulePreset")?.addEventListener("change", (event) => {
            if (event.target.value) applyPreset(event.target.value);
        });
        get("btnMentionAdd")?.addEventListener("click", () => {
            renderMentions([...readMentions(), ""]);
        });
        get("scheduleMentions")?.addEventListener("click", (event) => {
            const anyBtn = event.target.closest("[data-mention-any]");
            const removeBtn = event.target.closest("[data-mention-remove]");
            const row = event.target.closest("[data-mention-index]");
            if (!row) return;
            const items = readMentions();
            const index = Number(row.getAttribute("data-mention-index"));
            if (anyBtn) {
                const input = row.querySelector("[data-mention-input]");
                if (input) input.value = "*";
            }
            if (removeBtn) {
                items.splice(index, 1);
                renderMentions(items);
            }
        });
        document.querySelectorAll("[data-add-node]").forEach((button) => {
            button.addEventListener("click", () => {
                const start = startNode(readEditor());
                const nodes = readNodesFromCards(start);
                const added = defaultNode(button.getAttribute("data-add-node"));
                nodes.push(added);
                const last = nodes[nodes.length - 2];
                const edges = parseJsonText(
                    get("scheduleEdgesJson").value,
                    [],
                    "edges",
                );
                if (last && last.id)
                    edges.push({ from: last.id, to: added.id });
                if (added.type === "branch.if") {
                    edges.push({
                        from: added.id,
                        to: last?.id || "start",
                        case: "else",
                    });
                }
                get("scheduleEdgesJson").value = prettyJson(edges);
                renderNodes(nodes);
            });
        });
        get("scheduleNodes")?.addEventListener("click", (event) => {
            const remove = event.target.closest("[data-node-remove]");
            if (!remove) return;
            const card = event.target.closest(".schedule-node-card");
            card?.remove();
        });
        document.querySelectorAll("[data-var]").forEach((button) => {
            button.addEventListener("click", () => {
                const token = button.getAttribute("data-var");
                const target = scheduleState.lastFocused;
                if (!target || !token) return;
                const start = target.selectionStart || target.value.length;
                const end = target.selectionEnd || start;
                target.value =
                    target.value.slice(0, start) +
                    token +
                    target.value.slice(end);
                target.focus();
            });
        });
        document.addEventListener("focusin", (event) => {
            if (
                event.target &&
                (event.target.tagName === "TEXTAREA" ||
                    event.target.tagName === "INPUT")
            ) {
                scheduleState.lastFocused = event.target;
            }
        });
    }

    const controller = {
        init() {
            if (scheduleState.initialized) return;
            scheduleState.initialized = true;
            bindEvents();
            newTask();
        },
        onTabActivated(tab) {
            if (tab !== "schedules") return;
            if (typeof state !== "undefined" && !state.authenticated) return;
            if (!scheduleState.loaded) refresh();
        },
        refresh,
    };

    window.SchedulesController = controller;
})();
