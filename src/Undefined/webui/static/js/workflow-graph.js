(function () {
    const EVENT_KINDS = new Set([
        "message",
        "poke",
        "member_join",
        "member_leave",
    ]);
    const PALETTE_TYPES = [
        { id: "tool", group: "action" },
        { id: "template", group: "action" },
        { id: "llm.blank", group: "llm" },
        { id: "llm.agent", group: "llm" },
        { id: "llm.main", group: "llm" },
        { id: "branch.if", group: "branch" },
        { id: "branch.llm", group: "branch" },
        { id: "loop.times", group: "loop" },
        { id: "loop.each", group: "loop" },
    ];
    const NODE_WIDTH = 248;
    const NODE_MIN_HEIGHT = 86;
    const RANK_GAP_X = 300;
    const RANK_GAP_Y = 140;
    const LOOP_PAD = 48;

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function prettyJson(value) {
        return JSON.stringify(value === undefined ? null : value, null, 2);
    }

    function emptyTask() {
        return {
            task_name: "",
            enabled: true,
            consume_ai_loop: false,
            auto_send_final: false,
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
            ui: { positions: {}, zoom: 1, pan: { x: 40, y: 40 } },
        };
    }

    function defaultNode(type) {
        const id = `${String(type).replace(/[^a-z]/g, "_")}_${Math.random().toString(16).slice(2, 6)}`;
        if (type === "tool") {
            return {
                id,
                type,
                tool_name: "",
                args: {},
                emit: false,
                store_output: true,
                output_var: "",
            };
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
                toolsets: [],
                agents: [],
                emit: false,
                store_output: true,
                output_var: "",
                extract_vars: [],
            };
        }
        if (type === "llm.agent") {
            return {
                id,
                type,
                agent: "",
                input: "{{trigger.text}}",
                emit: false,
                store_output: true,
                output_var: "",
                extract_vars: [],
            };
        }
        if (type === "llm.main") {
            return {
                id,
                type,
                prompt: "{{trigger.text}}",
                emit: true,
                store_output: true,
                output_var: "",
                extract_vars: [],
            };
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
            return { id, type, count: 3, body: [], max_iterations: 25 };
        }
        return { id, type, source: "{{web}}", body: [], max_iterations: 25 };
    }

    function ensureUi(task) {
        if (!task.ui || typeof task.ui !== "object") {
            task.ui = { positions: {}, zoom: 1, pan: { x: 40, y: 40 } };
        }
        if (!task.ui.positions || typeof task.ui.positions !== "object") {
            task.ui.positions = {};
        }
        if (!task.ui.pan || typeof task.ui.pan !== "object") {
            task.ui.pan = { x: 40, y: 40 };
        }
        if (typeof task.ui.zoom !== "number") task.ui.zoom = 1;
        return task.ui;
    }

    function nodeMap(task) {
        const map = {};
        (task.nodes || []).forEach((node) => {
            if (node && node.id) map[node.id] = node;
        });
        return map;
    }

    function loopBodies(task) {
        const bodies = {};
        (task.nodes || []).forEach((node) => {
            if (
                !node ||
                (node.type !== "loop.times" && node.type !== "loop.each")
            ) {
                return;
            }
            bodies[node.id] = new Set(
                (node.body || []).map((item) => String(item)).filter(Boolean),
            );
        });
        return bodies;
    }

    function bodyOwners(task) {
        const owners = {};
        const bodies = loopBodies(task);
        Object.keys(bodies).forEach((loopId) => {
            bodies[loopId].forEach((nodeId) => {
                owners[nodeId] = loopId;
            });
        });
        return owners;
    }

    function sourceHandles(node) {
        if (!node) return [];
        if (node.type === "branch.if") {
            const cases = Array.isArray(node.cases) ? node.cases : [];
            return [
                ...cases.map((item) => ({
                    id: String(item.id || ""),
                    label: String(item.id || ""),
                })),
                { id: "else", label: "else" },
            ];
        }
        if (node.type === "branch.llm") {
            const options = Array.isArray(node.options) ? node.options : [];
            return options.map((item) => ({
                id: String(item.id || ""),
                label: String(item.id || ""),
            }));
        }
        if (node.type === "loop.times" || node.type === "loop.each") {
            return [{ id: "exit", label: "exit", kind: "exit" }];
        }
        return [{ id: "", label: "" }];
    }

    function nodeHeight(node) {
        const extras = sourceHandles(node).length;
        return NODE_MIN_HEIGHT + Math.max(0, extras - 1) * 18;
    }

    function outputVarLabel(node) {
        if (!node || node.store_output === false) return "";
        const name = String(node.output_var || "").trim();
        return name ? `{{${name}}}` : "";
    }

    function extractVarLabel(node) {
        return (node.extract_vars || [])
            .map((item) => String((item && item.name) || "").trim())
            .filter(Boolean)
            .map((name) => `{{${name}}}`)
            .join(" ");
    }

    function nodeSummary(node) {
        if (!node) return "";
        const stored = outputVarLabel(node);
        const extracted = extractVarLabel(node);
        const extras = [stored, extracted].filter(Boolean).join(" · ");
        const suffix = extras ? ` · ${extras}` : "";
        if (node.type === "start") return String(node.kind || "message");
        if (node.type === "tool")
            return `${String(node.tool_name || "")}${suffix}`.trim();
        if (node.type === "template")
            return String(node.template || "").slice(0, 48);
        if (node.type === "llm.agent")
            return `${String(node.agent || "")}${suffix}`.trim();
        if (node.type === "llm.main")
            return extras || String(node.prompt || "").slice(0, 48);
        if (node.type === "llm.blank") {
            if (extras) return extras;
            const allow = [
                ...(node.tools || []),
                ...(node.toolsets || []),
                ...(node.agents || []),
            ].filter(Boolean);
            return allow.length ? String(allow.length) : "blank";
        }
        if (node.type === "branch.if")
            return `${(node.cases || []).length} cases`;
        if (node.type === "branch.llm")
            return `${(node.options || []).length} options`;
        if (node.type === "loop.times") return `×${node.count || 0}`;
        if (node.type === "loop.each") return String(node.source || "");
        return node.type;
    }

    function incomingCount(task, nodeId) {
        return (task.edges || []).filter((edge) => edge && edge.to === nodeId)
            .length;
    }

    function canConnect(task, sourceId, targetId, extra) {
        if (!sourceId || !targetId || sourceId === targetId) {
            return "self-loop edges are not allowed";
        }
        const nodes = nodeMap(task);
        const source = nodes[sourceId];
        const target = nodes[targetId];
        if (!source || !target) return "unknown node";
        if (targetId === "start") return "cannot connect to start";
        const owners = bodyOwners(task);
        const bodies = loopBodies(task);
        if (bodies[sourceId] && owners[targetId] === sourceId) {
            return "loop body starts automatically";
        }
        if (
            owners[sourceId] &&
            owners[sourceId] !== owners[targetId] &&
            targetId !== owners[sourceId]
        ) {
            return "edges cannot cross loop body except loop exit";
        }
        if (
            owners[targetId] &&
            !owners[sourceId] &&
            sourceId !== owners[targetId]
        ) {
            return "connect to the loop node, not a body node";
        }
        if (source.type && String(source.type).startsWith("branch.")) {
            const handle =
                extra && extra.case != null ? String(extra.case) : "";
            if (!handle) return "branch edges require a case";
        }
        return "";
    }

    function normalizeEdge(source, extra) {
        const edge = { from: source.id, to: extra.to };
        if (source.type === "loop.times" || source.type === "loop.each") {
            edge.kind = "exit";
        }
        if (extra.case) edge.case = extra.case;
        if (extra.kind) edge.kind = extra.kind;
        return edge;
    }

    function stripCrossingEdges(task, nodeId) {
        const owners = bodyOwners(task);
        const owner = owners[nodeId];
        task.edges = (task.edges || []).filter((edge) => {
            if (!edge) return false;
            const fromOwner = owners[edge.from];
            const toOwner = owners[edge.to];
            if (edge.from !== nodeId && edge.to !== nodeId) return true;
            if (owner) {
                if (edge.from === owner || edge.to === owner) return true;
                return fromOwner === owner && toOwner === owner;
            }
            return !fromOwner && !toOwner;
        });
    }

    function autoLayout(task) {
        const ui = ensureUi(task);
        const nodes = task.nodes || [];
        const owners = bodyOwners(task);
        const outer = nodes.filter((node) => node && !owners[node.id]);
        const outgoing = {};
        (task.edges || []).forEach((edge) => {
            if (!edge || owners[edge.from] || owners[edge.to]) return;
            if (!outgoing[edge.from]) outgoing[edge.from] = [];
            outgoing[edge.from].push(edge.to);
        });
        const ranks = { start: 0 };
        const queue = ["start"];
        while (queue.length) {
            const current = queue.shift();
            (outgoing[current] || []).forEach((next) => {
                if (ranks[next] == null) {
                    ranks[next] = (ranks[current] || 0) + 1;
                    queue.push(next);
                }
            });
        }
        let maxRank = 0;
        outer.forEach((node) => {
            if (ranks[node.id] == null) {
                maxRank += 1;
                ranks[node.id] = maxRank;
            }
            maxRank = Math.max(maxRank, ranks[node.id] || 0);
        });
        const columns = {};
        outer.forEach((node) => {
            const rank = ranks[node.id] || 0;
            if (!columns[rank]) columns[rank] = [];
            columns[rank].push(node.id);
        });
        Object.keys(columns).forEach((rank) => {
            columns[rank].forEach((nodeId, index) => {
                ui.positions[nodeId] = {
                    x: Number(rank) * RANK_GAP_X,
                    y: index * RANK_GAP_Y,
                };
            });
        });
        const bodies = loopBodies(task);
        Object.keys(bodies).forEach((loopId) => {
            const origin = ui.positions[loopId] || { x: 0, y: 0 };
            let index = 0;
            bodies[loopId].forEach((nodeId) => {
                ui.positions[nodeId] = {
                    x: origin.x + 28,
                    y: origin.y + LOOP_PAD + index * (NODE_MIN_HEIGHT + 24),
                };
                index += 1;
            });
        });
        return ui;
    }

    function loopFrame(task, loopId) {
        const ui = ensureUi(task);
        const loop = nodeMap(task)[loopId];
        if (!loop) return null;
        const members = [loopId, ...Array.from(loopBodies(task)[loopId] || [])];
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        members.forEach((nodeId) => {
            const pos = ui.positions[nodeId] || { x: 0, y: 0 };
            const node = nodeMap(task)[nodeId];
            minX = Math.min(minX, pos.x);
            minY = Math.min(minY, pos.y);
            maxX = Math.max(maxX, pos.x + NODE_WIDTH);
            maxY = Math.max(maxY, pos.y + nodeHeight(node));
        });
        return {
            id: loopId,
            x: minX - 20,
            y: minY - 28,
            w: maxX - minX + 40,
            h: maxY - minY + 40,
        };
    }

    function createGraph(initial) {
        let task = clone(initial && initial.nodes ? initial : emptyTask());
        ensureUi(task);
        if (!Object.keys(task.ui.positions).length) autoLayout(task);
        let selectedId = "start";
        let selectedEdge = -1;
        const undo = [];
        const redo = [];
        const listeners = [];

        function snapshot() {
            return clone({
                task,
                selectedId,
                selectedEdge,
            });
        }

        function emit() {
            listeners.forEach((fn) => fn(getState()));
        }

        function pushHistory() {
            undo.push(snapshot());
            if (undo.length > 80) undo.shift();
            redo.length = 0;
        }

        function restore(entry) {
            task = clone(entry.task);
            selectedId = entry.selectedId;
            selectedEdge = entry.selectedEdge;
            ensureUi(task);
            emit();
        }

        function getState() {
            return {
                task,
                selectedId,
                selectedEdge,
                canUndo: undo.length > 0,
                canRedo: redo.length > 0,
            };
        }

        return {
            getState,
            subscribe(fn) {
                listeners.push(fn);
                return () => {
                    const index = listeners.indexOf(fn);
                    if (index >= 0) listeners.splice(index, 1);
                };
            },
            load(next) {
                task = clone(next && next.nodes ? next : emptyTask());
                ensureUi(task);
                if (!Object.keys(task.ui.positions).length) autoLayout(task);
                selectedId = "start";
                selectedEdge = -1;
                undo.length = 0;
                redo.length = 0;
                emit();
            },
            selectNode(nodeId) {
                selectedId = nodeId || "";
                selectedEdge = -1;
                emit();
            },
            selectEdge(index) {
                selectedEdge = index;
                selectedId = "";
                emit();
            },
            setMeta(patch) {
                pushHistory();
                Object.assign(task, patch);
                emit();
            },
            updateNode(nodeId, patch) {
                pushHistory();
                const node = nodeMap(task)[nodeId];
                if (node)
                    Object.assign(node, patch, {
                        id: node.id,
                        type: node.type,
                    });
                if (nodeId === "start") node.id = "start";
                emit();
            },
            renameNode(nodeId, nextId) {
                const id = String(nextId || "").trim();
                if (
                    !id ||
                    id === nodeId ||
                    nodeId === "start" ||
                    nodeMap(task)[id]
                ) {
                    return false;
                }
                pushHistory();
                const node = nodeMap(task)[nodeId];
                if (!node) return false;
                node.id = id;
                (task.edges || []).forEach((edge) => {
                    if (edge.from === nodeId) edge.from = id;
                    if (edge.to === nodeId) edge.to = id;
                });
                (task.nodes || []).forEach((item) => {
                    if (!Array.isArray(item.body)) return;
                    item.body = item.body.map((member) =>
                        member === nodeId ? id : member,
                    );
                });
                const ui = ensureUi(task);
                if (ui.positions[nodeId]) {
                    ui.positions[id] = ui.positions[nodeId];
                    delete ui.positions[nodeId];
                }
                selectedId = id;
                emit();
                return true;
            },
            moveNode(nodeId, x, y, record) {
                if (record) pushHistory();
                const ui = ensureUi(task);
                ui.positions[nodeId] = { x, y };
                emit();
            },
            setViewport(zoom, pan) {
                const ui = ensureUi(task);
                ui.zoom = zoom;
                ui.pan = pan;
            },
            addNode(type, position, connectFrom) {
                pushHistory();
                const node = defaultNode(type);
                task.nodes.push(node);
                const ui = ensureUi(task);
                ui.positions[node.id] = position || {
                    x: 240,
                    y: 80 + task.nodes.length * 24,
                };
                if (connectFrom && connectFrom.from) {
                    const source = nodeMap(task)[connectFrom.from];
                    const extra = {
                        to: node.id,
                        case: connectFrom.case || "",
                        kind: connectFrom.kind || "",
                    };
                    const error = canConnect(
                        task,
                        connectFrom.from,
                        node.id,
                        extra,
                    );
                    if (!error && source) {
                        task.edges.push(normalizeEdge(source, extra));
                    }
                }
                selectedId = node.id;
                selectedEdge = -1;
                emit();
                return node;
            },
            removeSelected() {
                if (selectedEdge >= 0) {
                    pushHistory();
                    task.edges.splice(selectedEdge, 1);
                    selectedEdge = -1;
                    emit();
                    return;
                }
                if (!selectedId || selectedId === "start") return;
                pushHistory();
                task.nodes = task.nodes.filter(
                    (node) => node.id !== selectedId,
                );
                task.edges = (task.edges || []).filter(
                    (edge) =>
                        edge.from !== selectedId && edge.to !== selectedId,
                );
                task.nodes.forEach((node) => {
                    if (Array.isArray(node.body)) {
                        node.body = node.body.filter(
                            (item) => item !== selectedId,
                        );
                    }
                });
                delete ensureUi(task).positions[selectedId];
                selectedId = "start";
                emit();
            },
            connect(fromId, toId, extra) {
                const payload = extra || {};
                const error = canConnect(task, fromId, toId, payload);
                if (error) return error;
                const exists = (task.edges || []).some(
                    (edge) =>
                        edge.from === fromId &&
                        edge.to === toId &&
                        String(edge.case || "") ===
                            String(payload.case || "") &&
                        String(edge.kind || "") === String(payload.kind || ""),
                );
                if (exists) return "";
                pushHistory();
                const source = nodeMap(task)[fromId];
                task.edges.push(
                    normalizeEdge(source, {
                        to: toId,
                        case: payload.case || "",
                        kind: payload.kind || "",
                    }),
                );
                emit();
                return "";
            },
            addToLoop(loopId, nodeId) {
                if (nodeId === "start" || loopId === nodeId) return;
                const loop = nodeMap(task)[loopId];
                if (
                    !loop ||
                    (loop.type !== "loop.times" && loop.type !== "loop.each")
                ) {
                    return;
                }
                pushHistory();
                const body = Array.isArray(loop.body) ? loop.body : [];
                if (!body.includes(nodeId)) body.push(nodeId);
                loop.body = body;
                task.nodes.forEach((node) => {
                    if (
                        node.id !== loopId &&
                        Array.isArray(node.body) &&
                        node.body.includes(nodeId)
                    ) {
                        node.body = node.body.filter((item) => item !== nodeId);
                    }
                });
                stripCrossingEdges(task, nodeId);
                emit();
            },
            removeFromLoop(nodeId) {
                const owners = bodyOwners(task);
                if (!owners[nodeId]) return;
                pushHistory();
                const loop = nodeMap(task)[owners[nodeId]];
                if (loop && Array.isArray(loop.body)) {
                    loop.body = loop.body.filter((item) => item !== nodeId);
                }
                stripCrossingEdges(task, nodeId);
                emit();
            },
            autoLayout() {
                pushHistory();
                autoLayout(task);
                emit();
            },
            undo() {
                const entry = undo.pop();
                if (!entry) return;
                redo.push(snapshot());
                restore(entry);
            },
            redo() {
                const entry = redo.pop();
                if (!entry) return;
                undo.push(snapshot());
                restore(entry);
            },
            payload() {
                const copy = clone(task);
                const {
                    max_executions: maxExecutions,
                    cooldown_seconds: cooldownSeconds,
                    address,
                    ...rest
                } = copy;
                const next = { ...rest };
                if (maxExecutions) next.max_executions = maxExecutions;
                if (cooldownSeconds != null && cooldownSeconds !== "") {
                    next.cooldown_seconds = cooldownSeconds;
                }
                if (address) next.address = address;
                return next;
            },
        };
    }

    window.WorkflowGraph = {
        EVENT_KINDS,
        PALETTE_TYPES,
        NODE_WIDTH,
        NODE_MIN_HEIGHT,
        LOOP_PAD,
        clone,
        prettyJson,
        emptyTask,
        defaultNode,
        ensureUi,
        nodeMap,
        loopBodies,
        bodyOwners,
        sourceHandles,
        nodeHeight,
        nodeSummary,
        incomingCount,
        canConnect,
        autoLayout,
        loopFrame,
        createGraph,
    };
})();
