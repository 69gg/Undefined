(function () {
    const G = window.WorkflowGraph;
    const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

    function field(labelKey, inner) {
        return `<div class="form-group"><label class="form-label">${escapeHtml(t(labelKey))}</label>${inner}</div>`;
    }

    function input(name, value, extra) {
        const attrs = extra || "";
        return `<input class="form-control" data-field="${escapeHtml(name)}" value="${escapeHtml(value || "")}" ${attrs} />`;
    }

    function textarea(name, value) {
        return `<textarea class="form-control form-textarea" data-field="${escapeHtml(name)}" data-var-target="1">${escapeHtml(value || "")}</textarea>`;
    }

    function select(name, value, options) {
        return `<select class="form-control" data-field="${escapeHtml(name)}">${options
            .map(
                (item) =>
                    `<option value="${escapeHtml(item.value)}"${item.value === value ? " selected" : ""}>${escapeHtml(item.label)}</option>`,
            )
            .join("")}</select>`;
    }

    function checkbox(name, checked, labelKey) {
        return `<label class="schedule-mode-option"><input type="checkbox" data-field="${escapeHtml(name)}"${checked ? " checked" : ""} /> <span>${escapeHtml(t(labelKey))}</span></label>`;
    }

    function nameList(items) {
        return (items || [])
            .map((item) => (typeof item === "string" ? item : item.name || ""))
            .filter(Boolean);
    }

    function renderStart(node, task) {
        const kind = String(node.kind || "message");
        const event = G.EVENT_KINDS.has(kind);
        const channels = new Set(node.channels || []);
        const clock =
            node.clock && typeof node.clock === "object" ? node.clock : {};
        const mentions = Array.isArray(node.mentions) ? node.mentions : [];
        const weekdays = new Set(clock.weekdays || []);
        return `
            ${field(
                "schedules.kind",
                select(
                    "kind",
                    kind,
                    [
                        "message",
                        "cron",
                        "daily",
                        "at",
                        "interval",
                        "poke",
                        "member_join",
                        "member_leave",
                    ].map((value) => ({
                        value,
                        label: t(`schedules.kind_${value}`) || value,
                    })),
                ),
            )}
            <div class="wf-chip-row">
                ${checkbox("enabled", task.enabled !== false, "schedules.enabled")}
                ${checkbox("consume_ai_loop", task.consume_ai_loop !== false, "schedules.consume")}
                ${checkbox("auto_send_final", task.auto_send_final !== false, "schedules.auto_send")}
            </div>
            ${field("schedules.target_address", input("address", task.address || "", `placeholder="group:123456"`))}
            ${field("schedules.max_executions", input("max_executions", task.max_executions || "", `type="number" min="1"`))}
            ${field("schedules.cooldown", input("cooldown_seconds", task.cooldown_seconds || "", `type="number" min="0"`))}
            <div class="wf-chip-row" data-start-event="${event ? "1" : "0"}" ${event ? "" : "hidden"}>
                ${checkbox("ch_group", channels.has("group"), "schedules.channel_group")}
                ${checkbox("ch_private", channels.has("private"), "schedules.channel_private")}
                ${checkbox("ch_wechat", channels.has("wechat"), "schedules.channel_wechat")}
            </div>
            <div ${event ? "" : "hidden"}>
                ${field("schedules.group_ids", input("group_ids", (node.group_ids || []).join(", ")))}
                ${field("schedules.user_ids", input("user_ids", (node.user_ids || []).join(", ")))}
                ${field(
                    "schedules.mentions",
                    `<div data-mentions="1">${mentions
                        .map(
                            (item, index) => `
                    <div class="schedule-mention-row" data-mention-index="${index}">
                        <input class="form-control" data-mention-input="1" value="${escapeHtml(item)}" />
                        <button type="button" class="btn ghost" data-mention-any="1">*</button>
                        <button type="button" class="btn ghost" data-mention-remove="1">×</button>
                    </div>`,
                        )
                        .join("")}</div>
                    <button type="button" class="btn ghost" data-mention-add="1">${escapeHtml(t("schedules.mention_add"))}</button>`,
                )}
                ${field("schedules.remain_text", input("text", node.text || "", `data-var-target="1"`))}
                ${field(
                    "schedules.text_match",
                    select("text_match", node.text_match || "contains", [
                        { value: "contains", label: "contains" },
                        { value: "keyword", label: "keyword" },
                        { value: "regex", label: "regex" },
                    ]),
                )}
                ${field(
                    "schedules.pass_text",
                    select("pass_text", node.pass_text || "stripped", [
                        { value: "stripped", label: "stripped" },
                        { value: "original", label: "original" },
                    ]),
                )}
                ${field("schedules.clock_after", input("clock_after", clock.after || "", `placeholder="09:00"`))}
                ${field("schedules.clock_before", input("clock_before", clock.before || "", `placeholder="18:00"`))}
                ${field(
                    "schedules.weekdays",
                    `<div class="wf-chip-row">${WEEKDAYS.map(
                        (day) =>
                            `<label class="schedule-mode-option"><input type="checkbox" data-weekday="${day}"${weekdays.has(day) ? " checked" : ""} /> ${day}</label>`,
                    ).join("")}</div>`,
                )}
            </div>
            <div ${kind === "cron" ? "" : "hidden"}>${field("schedules.cron", input("cron", node.cron || "", `placeholder="0 9 * * *"`))}</div>
            <div ${kind === "daily" ? "" : "hidden"}>${field("schedules.daily_time", input("time", node.time || "", `placeholder="09:00"`))}</div>
            <div ${kind === "at" ? "" : "hidden"}>${field("schedules.at", input("at", node.at || ""))}</div>
            <div ${kind === "interval" ? "" : "hidden"}>${field("schedules.interval", input("interval_seconds", node.interval_seconds || "", `type="number" min="1"`))}</div>
        `;
    }

    function optionSelect(name, value, names, allowCustom) {
        const options = [{ value: "", label: "—" }];
        names.forEach((item) => options.push({ value: item, label: item }));
        if (allowCustom && value && !names.includes(value)) {
            options.push({ value, label: value });
        }
        return select(name, value || "", options);
    }

    function renderNode(node, catalog) {
        const tools = nameList(catalog.tools);
        const agents = nameList(catalog.agents);
        const toolsets = nameList(catalog.toolsets);
        if (node.type === "tool") {
            const args = node.args || node.tool_args || {};
            const rows = Object.keys(args).length
                ? Object.entries(args)
                : [["", ""]];
            return `
                ${field("schedules.tool_name", optionSelect("tool_name", node.tool_name || "", tools, true))}
                ${field(
                    "schedules.tool_args",
                    `<div data-kv="args">${rows
                        .map(
                            ([key, value]) => `
                    <div class="wf-kv-row">
                        <input class="form-control" data-kv-key="1" value="${escapeHtml(key)}" placeholder="key" />
                        <input class="form-control" data-kv-value="1" data-var-target="1" value="${escapeHtml(String(value ?? ""))}" placeholder="value" />
                        <button type="button" class="btn ghost" data-kv-remove="1">×</button>
                    </div>`,
                        )
                        .join("")}</div>
                    <button type="button" class="btn ghost" data-kv-add="1">${escapeHtml(t("schedules.add_arg"))}</button>`,
                )}
                <div class="wf-chip-row">${checkbox("emit", Boolean(node.emit), "schedules.emit")}</div>`;
        }
        if (node.type === "template") {
            return `${field("schedules.template", textarea("template", node.template || ""))}
                <div class="wf-chip-row">${checkbox("emit", Boolean(node.emit), "schedules.emit")}</div>`;
        }
        if (node.type === "llm.blank") {
            return `
                ${field("schedules.system_prompt", textarea("system_prompt", node.system_prompt || ""))}
                ${field("schedules.user_prompt", textarea("user_prompt", node.user_prompt || ""))}
                ${field(
                    "schedules.tools",
                    `<select class="form-control" data-multi="tools" multiple>${tools
                        .map(
                            (name) =>
                                `<option value="${escapeHtml(name)}"${(node.tools || []).includes(name) ? " selected" : ""}>${escapeHtml(name)}</option>`,
                        )
                        .join("")}</select>`,
                )}
                ${field(
                    "schedules.toolsets",
                    `<select class="form-control" data-multi="toolsets" multiple>${toolsets
                        .map(
                            (name) =>
                                `<option value="${escapeHtml(name)}"${(node.toolsets || []).includes(name) ? " selected" : ""}>${escapeHtml(name)}</option>`,
                        )
                        .join("")}</select>`,
                )}
                ${field(
                    "schedules.agents",
                    `<select class="form-control" data-multi="agents" multiple>${agents
                        .map(
                            (name) =>
                                `<option value="${escapeHtml(name)}"${(node.agents || []).includes(name) ? " selected" : ""}>${escapeHtml(name)}</option>`,
                        )
                        .join("")}</select>`,
                )}
                <div class="wf-chip-row">${checkbox("emit", Boolean(node.emit), "schedules.emit")}</div>`;
        }
        if (node.type === "llm.agent") {
            return `${field("schedules.agent", optionSelect("agent", node.agent || "", agents, true))}
                ${field("schedules.input", input("input", node.input || "", `data-var-target="1"`))}
                <div class="wf-chip-row">${checkbox("emit", Boolean(node.emit), "schedules.emit")}</div>`;
        }
        if (node.type === "llm.main") {
            return `${field("schedules.prompt", textarea("prompt", node.prompt || ""))}
                <div class="wf-chip-row">${checkbox("emit", Boolean(node.emit), "schedules.emit")}</div>`;
        }
        if (node.type === "branch.if") {
            const cases = Array.isArray(node.cases) ? node.cases : [];
            return `${field("schedules.input", input("input", node.input || "", `data-var-target="1"`))}
                ${field(
                    "schedules.cases",
                    `<div data-cases="1">${cases
                        .map(
                            (item, index) => `
                    <div class="wf-case-row" data-case-index="${index}">
                        <input class="form-control" data-case-id="1" value="${escapeHtml(item.id || "")}" placeholder="id" />
                        <input class="form-control" data-case-text="1" data-var-target="1" value="${escapeHtml(item.text || "")}" placeholder="text" />
                        <button type="button" class="btn ghost" data-case-remove="1">×</button>
                    </div>`,
                        )
                        .join("")}</div>
                    <button type="button" class="btn ghost" data-case-add="1">${escapeHtml(t("schedules.add_case"))}</button>`,
                )}`;
        }
        if (node.type === "branch.llm") {
            const options = Array.isArray(node.options) ? node.options : [];
            return `${field("schedules.input", input("input", node.input || "", `data-var-target="1"`))}
                ${field(
                    "schedules.options",
                    `<div data-options="1">${options
                        .map(
                            (item, index) => `
                    <div class="wf-case-row" data-option-index="${index}">
                        <input class="form-control" data-option-id="1" value="${escapeHtml(item.id || "")}" placeholder="id" />
                        <input class="form-control" data-option-desc="1" value="${escapeHtml(item.description || "")}" />
                        <button type="button" class="btn ghost" data-option-remove="1">×</button>
                    </div>`,
                        )
                        .join("")}</div>
                    <button type="button" class="btn ghost" data-option-add="1">${escapeHtml(t("schedules.add_option"))}</button>`,
                )}`;
        }
        if (node.type === "loop.times") {
            return `${field("schedules.count", input("count", node.count || 3, `type="number" min="1" max="25"`))}
                ${field("schedules.max_iterations", input("max_iterations", node.max_iterations || 25, `type="number" min="1" max="25"`))}
                ${field("schedules.body", `<code>${escapeHtml((node.body || []).join(", ") || "—")}</code>`)}`;
        }
        if (node.type === "loop.each") {
            return `${field("schedules.source", input("source", node.source || "", `data-var-target="1"`))}
                ${field("schedules.max_iterations", input("max_iterations", node.max_iterations || 25, `type="number" min="1" max="25"`))}
                ${field("schedules.body", `<code>${escapeHtml((node.body || []).join(", ") || "—")}</code>`)}`;
        }
        return "";
    }

    function csvInts(value) {
        return String(value || "")
            .split(/[,，\s]+/)
            .map((item) => item.trim())
            .filter(Boolean)
            .map((item) => Number(item))
            .filter((item) => Number.isInteger(item));
    }

    function readStartPatch(root, node, task) {
        const fieldValue = (name) =>
            root.querySelector(`[data-field="${name}"]`);
        const kind = fieldValue("kind")?.value || "message";
        const patch = { kind };
        const meta = {
            enabled: !!root.querySelector('[data-field="enabled"]')?.checked,
            consume_ai_loop: !!root.querySelector(
                '[data-field="consume_ai_loop"]',
            )?.checked,
            auto_send_final: !!root.querySelector(
                '[data-field="auto_send_final"]',
            )?.checked,
            address: fieldValue("address")?.value.trim() || null,
        };
        const maxExec = String(
            fieldValue("max_executions")?.value || "",
        ).trim();
        meta.max_executions = maxExec ? Number(maxExec) : null;
        const cooldown = String(
            fieldValue("cooldown_seconds")?.value || "",
        ).trim();
        meta.cooldown_seconds = cooldown ? Number(cooldown) : null;
        if (G.EVENT_KINDS.has(kind)) {
            const channels = [];
            if (root.querySelector('[data-field="ch_group"]')?.checked)
                channels.push("group");
            if (root.querySelector('[data-field="ch_private"]')?.checked)
                channels.push("private");
            if (root.querySelector('[data-field="ch_wechat"]')?.checked)
                channels.push("wechat");
            patch.channels = channels;
            patch.group_ids = csvInts(fieldValue("group_ids")?.value);
            patch.user_ids = csvInts(fieldValue("user_ids")?.value);
            patch.mentions = Array.from(
                root.querySelectorAll("[data-mention-input]"),
            )
                .map((inputEl) => String(inputEl.value || "").trim())
                .filter(Boolean);
            patch.text = fieldValue("text")?.value.trim() || "";
            patch.text_match = fieldValue("text_match")?.value || "contains";
            patch.pass_text = fieldValue("pass_text")?.value || "stripped";
            const clock = {};
            if (fieldValue("clock_after")?.value.trim())
                clock.after = fieldValue("clock_after").value.trim();
            if (fieldValue("clock_before")?.value.trim())
                clock.before = fieldValue("clock_before").value.trim();
            const days = Array.from(
                root.querySelectorAll("[data-weekday]:checked"),
            ).map((el) => Number(el.getAttribute("data-weekday")));
            if (days.length) clock.weekdays = days;
            patch.clock = clock;
        }
        if (kind === "cron")
            patch.cron = fieldValue("cron")?.value.trim() || "";
        if (kind === "daily")
            patch.time = fieldValue("time")?.value.trim() || "";
        if (kind === "at") patch.at = fieldValue("at")?.value.trim() || "";
        if (kind === "interval")
            patch.interval_seconds = Number(
                fieldValue("interval_seconds")?.value || 0,
            );
        return { node: patch, meta };
    }

    function readKv(root) {
        const args = {};
        root.querySelectorAll("[data-kv] .wf-kv-row").forEach((row) => {
            const key = String(
                row.querySelector("[data-kv-key]")?.value || "",
            ).trim();
            const value = row.querySelector("[data-kv-value]")?.value;
            if (key) args[key] = value;
        });
        return args;
    }

    function variableItems(task, nodeId) {
        const items = [
            "{{trigger.text}}",
            "{{trigger.text_original}}",
            "{{trigger.text_stripped}}",
            "{{trigger.mentions}}",
            "{{trigger.channel}}",
            "{{trigger.sender_id}}",
            "{{trigger.nickname}}",
            "{{item}}",
            "{{index}}",
        ];
        (task.nodes || []).forEach((node) => {
            if (node.id && node.id !== nodeId && node.id !== "start") {
                items.push(`{{${node.id}}}`);
            }
        });
        return items;
    }

    function bindVarPicker(root, task, nodeId) {
        let menu = null;
        function close() {
            menu?.remove();
            menu = null;
        }
        root.addEventListener("focusin", (event) => {
            const target = event.target;
            if (!target || !target.hasAttribute("data-var-target")) return;
            close();
            menu = document.createElement("div");
            menu.className = "wf-var-menu";
            variableItems(task, nodeId).forEach((token) => {
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = token;
                button.addEventListener("mousedown", (clickEvent) => {
                    clickEvent.preventDefault();
                    const start = target.selectionStart || target.value.length;
                    const end = target.selectionEnd || start;
                    target.value = `${target.value.slice(0, start)}${token}${target.value.slice(end)}`;
                    target.dispatchEvent(
                        new Event("change", { bubbles: true }),
                    );
                    close();
                    target.focus();
                });
                menu.appendChild(button);
            });
            const rect = target.getBoundingClientRect();
            menu.style.left = `${rect.left}px`;
            menu.style.top = `${rect.bottom + 4}px`;
            document.body.appendChild(menu);
        });
        root.addEventListener("focusout", () => setTimeout(close, 120));
    }

    function createInspector(root, graph, catalogGetter) {
        function render() {
            const { task, selectedId, selectedEdge } = graph.getState();
            const catalog = catalogGetter() || {
                tools: [],
                agents: [],
                toolsets: [],
            };
            if (selectedEdge >= 0) {
                const edge = (task.edges || [])[selectedEdge] || {};
                root.innerHTML = `<h3>${escapeHtml(t("schedules.edge"))}</h3>
                    <p class="muted-sm">${escapeHtml(edge.from || "")} → ${escapeHtml(edge.to || "")}
                    ${edge.case ? ` · ${escapeHtml(edge.case)}` : ""}
                    ${edge.kind ? ` · ${escapeHtml(edge.kind)}` : ""}</p>
                    <button type="button" class="btn danger" data-remove-edge="1">${escapeHtml(t("schedules.node_remove"))}</button>`;
                return;
            }
            const node = G.nodeMap(task)[selectedId];
            if (!node) {
                root.innerHTML = `<p class="muted-sm">${escapeHtml(t("schedules.inspector_empty"))}</p>`;
                return;
            }
            const lastRun = [
                t("schedules.last_run"),
                task.last_status || "--",
                task.last_run_at || "",
                task.last_error || "",
            ]
                .filter(Boolean)
                .join(" · ");
            root.innerHTML = `
                <h3>${escapeHtml(t(`schedules.node_type.${node.type}`) || node.type)}</h3>
                ${field("schedules.node_id", `<input class="form-control" data-node-id-edit="1" value="${escapeHtml(node.id)}" ${node.id === "start" ? "disabled" : ""} />`)}
                ${node.type === "start" ? renderStart(node, task) : renderNode(node, catalog)}
                <p class="muted-sm">${escapeHtml(lastRun)}</p>
                ${task.next_run_time ? `<p class="muted-sm">${escapeHtml(t("schedules.next_run"))}: ${escapeHtml(task.next_run_time)}</p>` : ""}`;
            bindVarPicker(root, task, node.id);
        }

        function apply() {
            const { task, selectedId } = graph.getState();
            const node = G.nodeMap(task)[selectedId];
            if (!node) return;
            if (node.type === "start") {
                const result = readStartPatch(root, node, task);
                graph.setMeta(result.meta);
                graph.updateNode("start", result.node);
                return;
            }
            const patch = {};
            root.querySelectorAll("[data-field]").forEach((el) => {
                const name = el.getAttribute("data-field");
                if (el.type === "checkbox") patch[name] = el.checked;
                else if (el.type === "number")
                    patch[name] = el.value === "" ? null : Number(el.value);
                else patch[name] = el.value;
            });
            root.querySelectorAll("[data-multi]").forEach((el) => {
                patch[el.getAttribute("data-multi")] = Array.from(
                    el.selectedOptions,
                ).map((option) => option.value);
            });
            if (node.type === "tool") patch.args = readKv(root);
            if (node.type === "branch.if") {
                patch.cases = Array.from(
                    root.querySelectorAll("[data-case-index]"),
                ).map((row) => ({
                    id: row.querySelector("[data-case-id]")?.value.trim() || "",
                    text: row.querySelector("[data-case-text]")?.value || "",
                }));
            }
            if (node.type === "branch.llm") {
                patch.options = Array.from(
                    root.querySelectorAll("[data-option-index]"),
                ).map((row) => ({
                    id:
                        row.querySelector("[data-option-id]")?.value.trim() ||
                        "",
                    description:
                        row.querySelector("[data-option-desc]")?.value || "",
                }));
            }
            const nextId = root
                .querySelector("[data-node-id-edit]")
                ?.value.trim();
            if (nextId && nextId !== node.id) graph.renameNode(node.id, nextId);
            graph.updateNode(graph.getState().selectedId || node.id, patch);
        }

        root.addEventListener("change", (event) => {
            apply();
            if (
                event.target &&
                event.target.getAttribute("data-field") === "kind"
            ) {
                render();
            }
        });
        root.addEventListener("click", (event) => {
            if (event.target.closest("[data-remove-edge]")) {
                graph.removeSelected();
                return;
            }
            if (event.target.closest("[data-mention-add]")) {
                const box = root.querySelector("[data-mentions]");
                if (box) {
                    box.insertAdjacentHTML(
                        "beforeend",
                        `<div class="schedule-mention-row"><input class="form-control" data-mention-input="1" /><button type="button" class="btn ghost" data-mention-any="1">*</button><button type="button" class="btn ghost" data-mention-remove="1">×</button></div>`,
                    );
                }
                return;
            }
            const mentionRow = event.target.closest(
                "[data-mention-index], .schedule-mention-row",
            );
            if (event.target.closest("[data-mention-any]") && mentionRow) {
                const inputEl = mentionRow.querySelector(
                    "[data-mention-input]",
                );
                if (inputEl) inputEl.value = "*";
                apply();
                return;
            }
            if (event.target.closest("[data-mention-remove]") && mentionRow) {
                mentionRow.remove();
                apply();
                return;
            }
            if (event.target.closest("[data-kv-add]")) {
                root.querySelector("[data-kv]")?.insertAdjacentHTML(
                    "beforeend",
                    `<div class="wf-kv-row"><input class="form-control" data-kv-key="1" /><input class="form-control" data-kv-value="1" data-var-target="1" /><button type="button" class="btn ghost" data-kv-remove="1">×</button></div>`,
                );
                return;
            }
            if (event.target.closest("[data-kv-remove]")) {
                event.target.closest(".wf-kv-row")?.remove();
                apply();
                return;
            }
            if (event.target.closest("[data-case-add]")) {
                root.querySelector("[data-cases]")?.insertAdjacentHTML(
                    "beforeend",
                    `<div class="wf-case-row" data-case-index="x"><input class="form-control" data-case-id="1" /><input class="form-control" data-case-text="1" data-var-target="1" /><button type="button" class="btn ghost" data-case-remove="1">×</button></div>`,
                );
                return;
            }
            if (event.target.closest("[data-case-remove]")) {
                event.target.closest("[data-case-index]")?.remove();
                apply();
                return;
            }
            if (event.target.closest("[data-option-add]")) {
                root.querySelector("[data-options]")?.insertAdjacentHTML(
                    "beforeend",
                    `<div class="wf-case-row" data-option-index="x"><input class="form-control" data-option-id="1" /><input class="form-control" data-option-desc="1" /><button type="button" class="btn ghost" data-option-remove="1">×</button></div>`,
                );
                return;
            }
            if (event.target.closest("[data-option-remove]")) {
                event.target.closest("[data-option-index]")?.remove();
                apply();
            }
        });

        let selectionKey = "";
        graph.subscribe(() => {
            const { selectedId, selectedEdge } = graph.getState();
            const key = `${selectedId}:${selectedEdge}`;
            if (key !== selectionKey) {
                selectionKey = key;
                render();
            }
        });
        render();
        return {
            render() {
                const { selectedId, selectedEdge } = graph.getState();
                selectionKey = `${selectedId}:${selectedEdge}`;
                render();
            },
        };
    }

    window.WorkflowInspector = { createInspector };
})();
