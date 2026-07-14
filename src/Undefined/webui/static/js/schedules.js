(function () {
    const SELF_TOOL_NAME = "scheduler.call_self";

    const scheduleState = {
        initialized: false,
        loaded: false,
        busy: false,
        tasks: [],
        selectedId: "",
        draftNew: true,
        search: "",
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

    function singleSelfTool(task) {
        return (
            Array.isArray(task.tools) &&
            task.tools.length === 1 &&
            task.tools[0] &&
            task.tools[0].tool_name === SELF_TOOL_NAME
        );
    }

    function selfInstructionOfTask(task) {
        const explicit = String(task.self_instruction || "").trim();
        if (explicit) return explicit;
        if (task.tool_name === SELF_TOOL_NAME && task.tool_args) {
            return String(task.tool_args.prompt || "").trim();
        }
        if (singleSelfTool(task) && task.tools[0].tool_args) {
            return String(task.tools[0].tool_args.prompt || "").trim();
        }
        return "";
    }

    function modeOfTask(task) {
        if (singleSelfTool(task)) return "self_instruction";
        if (task.mode === "multi" || task.mode === "self_instruction") {
            return task.mode;
        }
        if (task.mode === "single") return "single";
        if (task.self_instruction || task.tool_name === SELF_TOOL_NAME) {
            return "self_instruction";
        }
        if (Array.isArray(task.tools) && task.tools.length) return "multi";
        return "single";
    }

    function modeLabel(mode) {
        if (mode === "self_instruction") return t("schedules.mode_self");
        if (mode === "multi") return t("schedules.mode_multi");
        return t("schedules.mode_single");
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
        scheduleState.busy = !!loading;
        [
            "btnSchedulesRefresh",
            "btnSchedulesNew",
            "btnScheduleReset",
            "btnScheduleDelete",
            "btnScheduleSave",
        ].forEach((id) => {
            const button = get(id);
            if (button) button.disabled = scheduleState.busy;
        });
    }

    function updateSummary() {
        const total = scheduleState.tasks.length;
        const selfCount = scheduleState.tasks.filter(
            (task) => modeOfTask(task) === "self_instruction",
        ).length;
        const multiCount = scheduleState.tasks.filter(
            (task) => modeOfTask(task) === "multi",
        ).length;
        const limitedCount = scheduleState.tasks.filter(
            (task) =>
                task.max_executions !== null &&
                task.max_executions !== undefined,
        ).length;
        const values = {
            scheduleStatTotal: total,
            scheduleStatSelf: selfCount,
            scheduleStatMulti: multiCount,
            scheduleStatLimited: limitedCount,
        };
        Object.entries(values).forEach(([id, value]) => {
            const el = get(id);
            if (el) el.textContent = String(value);
        });
    }

    function filteredTasks() {
        const query = scheduleState.search.trim().toLowerCase();
        if (!query) return scheduleState.tasks;
        return scheduleState.tasks.filter((task) => {
            const haystack = [
                task.task_id,
                task.task_name,
                task.cron,
                task.tool_name,
                task.self_instruction,
                task.address,
                task.target_id,
                task.target_type,
            ]
                .map((value) => String(value || "").toLowerCase())
                .join(" ");
            return haystack.includes(query);
        });
    }

    function renderList() {
        updateSummary();
        const list = get("scheduleList");
        if (!list) return;
        const items = filteredTasks();
        if (!items.length) {
            list.innerHTML = `<div class="empty-state">${escapeHtml(
                scheduleState.tasks.length
                    ? t("schedules.no_results")
                    : t("schedules.empty"),
            )}</div>`;
            return;
        }
        list.innerHTML = items
            .map((task) => {
                const taskId = String(task.task_id || "");
                const selected = taskId === scheduleState.selectedId;
                const mode = modeOfTask(task);
                const nextRun = formatDateTime(task.next_run_time);
                const target = taskAddress(task) || t("schedules.no_target");
                return `<button class="schedule-list-item${selected ? " is-selected" : ""}" type="button" data-task-id="${escapeHtml(taskId)}">
                    <span class="schedule-list-main">
                        <span class="schedule-list-title">${escapeHtml(taskTitle(task))}</span>
                        <span class="schedule-list-sub"><code>${escapeHtml(task.cron || "--")}</code></span>
                    </span>
                    <span class="schedule-list-meta">
                        <span class="runtime-tag">${escapeHtml(modeLabel(mode))}</span>
                        <span>${escapeHtml(target)}</span>
                        <span>${escapeHtml(t("schedules.next_run"))}: ${escapeHtml(nextRun)}</span>
                    </span>
                </button>`;
            })
            .join("");
        list.querySelectorAll("[data-task-id]").forEach((item) => {
            item.addEventListener("click", () => {
                selectTask(item.getAttribute("data-task-id") || "");
            });
        });
    }

    function setMode(mode) {
        const normalized =
            mode === "multi" || mode === "self_instruction" ? mode : "single";
        document
            .querySelectorAll('input[name="scheduleMode"]')
            .forEach((input) => {
                input.checked = input.value === normalized;
            });
        const single = get("scheduleSingleFields");
        const multi = get("scheduleMultiFields");
        const self = get("scheduleSelfFields");
        if (single)
            single.style.display = normalized === "single" ? "" : "none";
        if (multi) multi.style.display = normalized === "multi" ? "" : "none";
        if (self)
            self.style.display =
                normalized === "self_instruction" ? "" : "none";
        const badge = get("scheduleEditorBadge");
        if (badge) badge.textContent = modeLabel(normalized);
    }

    function currentMode() {
        const checked = document.querySelector(
            'input[name="scheduleMode"]:checked',
        );
        return checked ? checked.value : "single";
    }

    function taskAddress(task) {
        const explicit = String(task?.address || "").trim();
        if (explicit) return explicit;
        if (!task?.target_id) return "";
        const channel = task.target_type === "group" ? "group" : "qq";
        return `${channel}:${task.target_id}`;
    }

    function emptyDraft() {
        return {
            task_id: "",
            task_name: "",
            cron: "0 9 * * *",
            address: "",
            target_type: "group",
            target_id: null,
            max_executions: null,
            tool_name: "",
            tool_args: {},
            tools: [],
            execution_mode: "serial",
            self_instruction: "",
        };
    }

    function populateEditor(task, isNew) {
        scheduleState.draftNew = !!isNew;
        const source = task || emptyDraft();
        const taskIdInput = get("scheduleTaskId");
        if (taskIdInput) {
            taskIdInput.value = source.task_id || "";
            taskIdInput.disabled = !scheduleState.draftNew;
        }
        const fields = {
            scheduleTaskName: source.task_name || "",
            scheduleCron: source.cron || "0 9 * * *",
            scheduleTargetAddress: taskAddress(source),
            scheduleMaxExecutions: source.max_executions || "",
            scheduleToolName:
                source.tool_name === SELF_TOOL_NAME
                    ? ""
                    : source.tool_name || "",
            scheduleSelfInstruction: selfInstructionOfTask(source),
        };
        Object.entries(fields).forEach(([id, value]) => {
            const el = get(id);
            if (el) el.value = String(value || "");
        });
        const executionMode = get("scheduleExecutionMode");
        if (executionMode)
            executionMode.value = source.execution_mode || "serial";
        const args = get("scheduleToolArgs");
        if (args) args.value = prettyJson(source.tool_args || {});
        const tools = get("scheduleToolsJson");
        if (tools) {
            const value =
                Array.isArray(source.tools) && source.tools.length
                    ? source.tools
                    : source.tool_name
                      ? [
                            {
                                tool_name: source.tool_name,
                                tool_args: source.tool_args || {},
                            },
                        ]
                      : [];
            tools.value = prettyJson(value);
        }
        const label = get("scheduleEditorModeLabel");
        if (label)
            label.textContent = scheduleState.draftNew
                ? t("schedules.editor_new")
                : t("schedules.editor_edit");
        const editorId = get("scheduleEditorTaskId");
        if (editorId) editorId.textContent = source.task_id || "--";
        const deleteBtn = get("btnScheduleDelete");
        if (deleteBtn)
            deleteBtn.style.display = scheduleState.draftNew ? "none" : "";
        setMode(modeOfTask(source));
        setStatus("");
    }

    function selectTask(taskId) {
        const task = scheduleState.tasks.find(
            (item) => item.task_id === taskId,
        );
        if (!task) return;
        scheduleState.selectedId = taskId;
        populateEditor(task, false);
        renderList();
    }

    function newTask() {
        scheduleState.selectedId = "";
        populateEditor(emptyDraft(), true);
        renderList();
    }

    function readPositiveInt(id, label) {
        const el = get(id);
        const raw = String((el && el.value) || "").trim();
        if (!raw) return null;
        const value = Number.parseInt(raw, 10);
        if (!Number.isFinite(value) || value < 1) {
            throw new Error(
                i18nFormat("schedules.positive_int_error", { label }),
            );
        }
        return value;
    }

    function buildPayload() {
        const mode = currentMode();
        const cron = String(get("scheduleCron")?.value || "").trim();
        if (!cron) throw new Error(t("schedules.cron_required"));
        const payload = {
            mode,
            task_name: String(get("scheduleTaskName")?.value || "").trim(),
            cron_expression: cron,
            address:
                String(get("scheduleTargetAddress")?.value || "").trim() ||
                null,
            max_executions: readPositiveInt(
                "scheduleMaxExecutions",
                t("schedules.max_executions"),
            ),
        };
        if (scheduleState.draftNew) {
            const taskId = String(get("scheduleTaskId")?.value || "").trim();
            if (taskId) payload.task_id = taskId;
        }

        if (mode === "self_instruction") {
            const instruction = String(
                get("scheduleSelfInstruction")?.value || "",
            ).trim();
            if (!instruction) throw new Error(t("schedules.self_required"));
            payload.self_instruction = instruction;
            return payload;
        }

        if (mode === "multi") {
            const tools = parseJsonText(
                get("scheduleToolsJson")?.value,
                [],
                t("schedules.tools_json"),
            );
            if (!Array.isArray(tools) || tools.length === 0) {
                throw new Error(t("schedules.tools_required"));
            }
            payload.tools = tools;
            payload.execution_mode = String(
                get("scheduleExecutionMode")?.value || "serial",
            );
            return payload;
        }

        const toolName = String(get("scheduleToolName")?.value || "").trim();
        if (!toolName) throw new Error(t("schedules.tool_required"));
        payload.tool_name = toolName;
        payload.tool_args = parseJsonText(
            get("scheduleToolArgs")?.value,
            {},
            t("schedules.tool_args"),
        );
        return payload;
    }

    async function refresh() {
        setBusy(true);
        setPageStatus(t("common.loading"));
        try {
            const response = await api("/api/runtime/schedules", {
                signal: getAbortSignal("schedules"),
            });
            const payload = await parseJsonSafe(response);
            if (!response.ok || (payload && payload.error)) {
                throw new Error(requestError(response, payload));
            }
            scheduleState.tasks = Array.isArray(payload?.items)
                ? payload.items
                : [];
            scheduleState.loaded = true;
            setPageStatus(
                i18nFormat("schedules.loaded", {
                    count: scheduleState.tasks.length,
                }),
            );
            if (scheduleState.selectedId) {
                const selected = scheduleState.tasks.find(
                    (task) => task.task_id === scheduleState.selectedId,
                );
                if (selected) populateEditor(selected, false);
                else newTask();
            } else if (!scheduleState.draftNew && scheduleState.tasks.length) {
                selectTask(scheduleState.tasks[0].task_id);
            } else {
                populateEditor(emptyDraft(), true);
            }
            renderList();
        } catch (error) {
            if (error?.name === "AbortError") return;
            setPageStatus(t("runtime.failed"));
            showToast(
                `${t("runtime.failed")}: ${error.message || error}`,
                "error",
                5000,
            );
        } finally {
            setBusy(false);
        }
    }

    async function save(event) {
        if (event) event.preventDefault();
        if (scheduleState.busy) return;
        let payload;
        try {
            payload = buildPayload();
        } catch (error) {
            setStatus(error.message || String(error), "error");
            return;
        }
        setBusy(true);
        setStatus(t("config.saving"));
        try {
            const url = scheduleState.draftNew
                ? "/api/runtime/schedules"
                : `/api/runtime/schedules/${encodeURIComponent(scheduleState.selectedId)}`;
            const response = await api(url, {
                method: scheduleState.draftNew ? "POST" : "PATCH",
                body: JSON.stringify(payload),
            });
            const data = await parseJsonSafe(response);
            if (!response.ok || (data && data.error)) {
                throw new Error(requestError(response, data));
            }
            const task = data?.task || null;
            if (task?.task_id) {
                scheduleState.selectedId = task.task_id;
                const index = scheduleState.tasks.findIndex(
                    (item) => item.task_id === task.task_id,
                );
                if (index >= 0) scheduleState.tasks.splice(index, 1, task);
                else scheduleState.tasks.unshift(task);
                populateEditor(task, false);
            }
            renderList();
            setStatus(t("schedules.saved"), "success");
            showToast(t("schedules.saved"), "success");
            await refresh();
        } catch (error) {
            setStatus(error.message || String(error), "error");
            showToast(
                `${t("schedules.save_failed")}: ${error.message || error}`,
                "error",
                5000,
            );
        } finally {
            setBusy(false);
        }
    }

    async function removeSelected() {
        if (
            scheduleState.draftNew ||
            !scheduleState.selectedId ||
            scheduleState.busy
        )
            return;
        if (!confirm(t("schedules.confirm_delete"))) return;
        setBusy(true);
        try {
            const response = await api(
                `/api/runtime/schedules/${encodeURIComponent(scheduleState.selectedId)}`,
                { method: "DELETE" },
            );
            const payload = await parseJsonSafe(response);
            if (!response.ok || (payload && payload.error)) {
                throw new Error(requestError(response, payload));
            }
            scheduleState.tasks = scheduleState.tasks.filter(
                (task) => task.task_id !== scheduleState.selectedId,
            );
            showToast(t("schedules.deleted"), "success");
            newTask();
            renderList();
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

    function bindEvents() {
        get("btnSchedulesRefresh")?.addEventListener("click", refresh);
        get("btnSchedulesNew")?.addEventListener("click", newTask);
        get("btnScheduleReset")?.addEventListener("click", () => {
            if (scheduleState.selectedId) selectTask(scheduleState.selectedId);
            else newTask();
        });
        get("btnScheduleDelete")?.addEventListener("click", () => {
            removeSelected();
        });
        get("scheduleEditor")?.addEventListener("submit", save);
        get("scheduleSearchInput")?.addEventListener("input", (event) => {
            scheduleState.search = String(event.target.value || "");
            renderList();
        });
        document
            .querySelectorAll('input[name="scheduleMode"]')
            .forEach((input) => {
                input.addEventListener("change", () => setMode(input.value));
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
