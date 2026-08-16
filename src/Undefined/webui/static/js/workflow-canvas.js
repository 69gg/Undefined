(function () {
    const G = window.WorkflowGraph;
    const SWATCH = {
        start: "#d97757",
        tool: "#4a7c59",
        template: "#cc8925",
        "llm.blank": "#6b7aa1",
        "llm.agent": "#6b7aa1",
        "llm.main": "#6b7aa1",
        "branch.if": "#8a6a9a",
        "branch.llm": "#8a6a9a",
        "loop.times": "#3d7a8c",
        "loop.each": "#3d7a8c",
    };

    function typeLabel(type) {
        return t(`schedules.node_type.${type}`) || type;
    }

    function bezier(x1, y1, x2, y2) {
        const dx = Math.max(48, Math.abs(x2 - x1) * 0.45);
        return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
    }

    function handlePositions(node, pos) {
        const handles = G.sourceHandles(node);
        const height = G.nodeHeight(node);
        const ins =
            node.id === "start"
                ? []
                : [{ id: "in", x: pos.x, y: pos.y + height / 2 }];
        const outs = handles.map((handle, index) => {
            const span = handles.length === 1 ? height / 2 : 22 + index * 18;
            return {
                id: handle.id,
                kind: handle.kind || "",
                label: handle.label,
                x: pos.x + G.NODE_WIDTH,
                y: pos.y + span,
            };
        });
        return { ins, outs };
    }

    function createCanvas(root, graph, options) {
        const opts = options || {};
        let drag = null;
        let connect = null;
        let panDrag = null;
        let spaceDown = false;

        root.innerHTML = `
            <div class="wf-world">
                <svg class="wf-edges"></svg>
                <div class="wf-nodes"></div>
            </div>`;
        const world = root.querySelector(".wf-world");
        const svg = root.querySelector(".wf-edges");
        const nodesLayer = root.querySelector(".wf-nodes");

        function uiState() {
            return graph.getState();
        }

        function worldPoint(event) {
            const rect = root.getBoundingClientRect();
            const { task } = uiState();
            const ui = G.ensureUi(task);
            return {
                x: (event.clientX - rect.left - ui.pan.x) / ui.zoom,
                y: (event.clientY - rect.top - ui.pan.y) / ui.zoom,
            };
        }

        function applyTransform() {
            const { task } = uiState();
            const ui = G.ensureUi(task);
            world.style.transform = `translate(${ui.pan.x}px, ${ui.pan.y}px) scale(${ui.zoom})`;
        }

        function nodeAt(point) {
            const { task } = uiState();
            const ui = G.ensureUi(task);
            let hit = null;
            (task.nodes || []).forEach((node) => {
                const pos = ui.positions[node.id] || { x: 0, y: 0 };
                if (
                    point.x >= pos.x &&
                    point.x <= pos.x + G.NODE_WIDTH &&
                    point.y >= pos.y &&
                    point.y <= pos.y + G.nodeHeight(node)
                ) {
                    hit = node;
                }
            });
            return hit;
        }

        function loopAt(point, ignoreId) {
            const { task } = uiState();
            let found = null;
            (task.nodes || []).forEach((node) => {
                if (node.type !== "loop.times" && node.type !== "loop.each")
                    return;
                if (node.id === ignoreId) return;
                const frame = G.loopFrame(task, node.id);
                if (
                    frame &&
                    point.x >= frame.x &&
                    point.x <= frame.x + frame.w &&
                    point.y >= frame.y &&
                    point.y <= frame.y + frame.h
                ) {
                    found = node.id;
                }
            });
            return found;
        }

        function render() {
            const { task, selectedId, selectedEdge } = uiState();
            const ui = G.ensureUi(task);
            applyTransform();
            nodesLayer.innerHTML = "";
            svg.replaceChildren();
            (task.nodes || []).forEach((node) => {
                if (node.type === "loop.times" || node.type === "loop.each") {
                    const frame = G.loopFrame(task, node.id);
                    if (!frame) return;
                    const box = document.createElement("div");
                    box.className = "wf-loop-frame";
                    box.style.left = `${frame.x}px`;
                    box.style.top = `${frame.y}px`;
                    box.style.width = `${frame.w}px`;
                    box.style.height = `${frame.h}px`;
                    box.innerHTML = `<div class="wf-loop-caption">${escapeHtml(typeLabel(node.type))}</div>`;
                    nodesLayer.appendChild(box);
                }
            });
            (task.edges || []).forEach((edge, index) => {
                const from = G.nodeMap(task)[edge.from];
                const to = G.nodeMap(task)[edge.to];
                if (!from || !to) return;
                const fromPos = ui.positions[from.id] || { x: 0, y: 0 };
                const toPos = ui.positions[to.id] || { x: 0, y: 0 };
                const outs = handlePositions(from, fromPos).outs;
                const target = handlePositions(to, toPos).ins[0] || {
                    x: toPos.x,
                    y: toPos.y + G.nodeHeight(to) / 2,
                };
                let origin = outs[0] || {
                    x: fromPos.x + G.NODE_WIDTH,
                    y: fromPos.y + G.nodeHeight(from) / 2,
                };
                if (edge.case) {
                    const matched = outs.find((item) => item.id === edge.case);
                    if (matched) origin = matched;
                }
                if (edge.kind === "exit") {
                    const matched = outs.find((item) => item.kind === "exit");
                    if (matched) origin = matched;
                }
                const path = document.createElementNS(
                    "http://www.w3.org/2000/svg",
                    "path",
                );
                path.setAttribute(
                    "d",
                    bezier(origin.x, origin.y, target.x, target.y),
                );
                path.setAttribute(
                    "class",
                    `wf-edge-path${selectedEdge === index ? " is-selected" : ""}`,
                );
                path.dataset.edgeIndex = String(index);
                path.style.pointerEvents = "stroke";
                path.addEventListener("pointerdown", (event) => {
                    event.stopPropagation();
                    graph.selectEdge(index);
                });
                svg.appendChild(path);
            });
            (task.nodes || []).forEach((node) => {
                const pos = ui.positions[node.id] || { x: 0, y: 0 };
                const el = document.createElement("div");
                el.className = "wf-node";
                el.dataset.nodeId = node.id;
                if (selectedId === node.id) el.classList.add("is-selected");
                if (
                    task.last_status === "failed" &&
                    task.last_node_id === node.id
                ) {
                    el.classList.add("is-failed");
                }
                el.style.left = `${pos.x}px`;
                el.style.top = `${pos.y}px`;
                el.style.height = `${G.nodeHeight(node)}px`;
                el.style.setProperty(
                    "--wf-swatch",
                    SWATCH[node.type] || "#d97757",
                );
                const andJoin = G.incomingCount(task, node.id) > 1;
                el.innerHTML = `
                    ${andJoin ? `<span class="wf-and-badge">AND</span>` : ""}
                    <div class="wf-node-type">${escapeHtml(typeLabel(node.type))}</div>
                    <div class="wf-node-title">${escapeHtml(node.id)}</div>
                    <div class="wf-node-sub">${escapeHtml(G.nodeSummary(node))}</div>`;
                const handles = handlePositions(node, pos);
                if (node.id !== "start") {
                    const inbound = document.createElement("span");
                    inbound.className = "wf-handle is-in";
                    inbound.dataset.nodeId = node.id;
                    inbound.dataset.handle = "in";
                    el.appendChild(inbound);
                }
                handles.outs.forEach((handle, index) => {
                    const outbound = document.createElement("span");
                    outbound.className = "wf-handle is-out";
                    outbound.style.top = `${handles.outs[index].y - pos.y}px`;
                    outbound.dataset.nodeId = node.id;
                    outbound.dataset.handle = handle.id;
                    outbound.dataset.kind = handle.kind || "";
                    if (handle.label) {
                        const label = document.createElement("span");
                        label.className = "wf-handle-label";
                        label.style.top = outbound.style.top;
                        label.textContent = handle.label;
                        el.appendChild(label);
                    }
                    outbound.addEventListener("pointerdown", (event) => {
                        event.stopPropagation();
                        event.preventDefault();
                        connect = {
                            from: node.id,
                            case: handle.id,
                            kind: handle.kind || "",
                        };
                    });
                    el.appendChild(outbound);
                });
                el.addEventListener("pointerdown", (event) => {
                    if (event.target.closest(".wf-handle")) return;
                    graph.selectNode(node.id);
                    const start = worldPoint(event);
                    drag = {
                        id: node.id,
                        dx: start.x - pos.x,
                        dy: start.y - pos.y,
                        moved: false,
                    };
                });
                nodesLayer.appendChild(el);
            });
            if (typeof opts.onRender === "function") opts.onRender(uiState());
        }

        function finishConnect(event) {
            if (!connect) return;
            const point = worldPoint(event);
            const target = nodeAt(point);
            if (target) {
                const extra = {
                    case: connect.case || "",
                    kind: connect.kind || "",
                };
                const error = graph.connect(connect.from, target.id, extra);
                if (error && typeof showToast === "function") {
                    showToast(error, "error", 2800);
                }
            }
            connect = null;
            const ghost = svg.querySelector("[data-ghost]");
            if (ghost) ghost.remove();
        }

        root.addEventListener("pointerdown", (event) => {
            if (
                event.target === root ||
                event.target === world ||
                event.target === svg
            ) {
                if (spaceDown || event.button === 1 || event.altKey) {
                    panDrag = {
                        x: event.clientX,
                        y: event.clientY,
                        pan: { ...G.ensureUi(uiState().task).pan },
                    };
                    root.classList.add("is-panning");
                    return;
                }
                graph.selectNode("");
            }
        });
        window.addEventListener("pointermove", (event) => {
            if (panDrag) {
                const ui = G.ensureUi(uiState().task);
                graph.setViewport(ui.zoom, {
                    x: panDrag.pan.x + (event.clientX - panDrag.x),
                    y: panDrag.pan.y + (event.clientY - panDrag.y),
                });
                applyTransform();
                return;
            }
            if (drag) {
                const point = worldPoint(event);
                const x = point.x - drag.dx;
                const y = point.y - drag.dy;
                drag.moved = true;
                const nodeEl = nodesLayer.querySelector(
                    `[data-node-id="${CSS.escape(drag.id)}"]`,
                );
                if (nodeEl) {
                    nodeEl.style.left = `${x}px`;
                    nodeEl.style.top = `${y}px`;
                }
                drag.x = x;
                drag.y = y;
                return;
            }
            if (connect) {
                const { task } = uiState();
                const ui = G.ensureUi(task);
                const from = G.nodeMap(task)[connect.from];
                const fromPos = ui.positions[from.id] || { x: 0, y: 0 };
                const outs = handlePositions(from, fromPos).outs;
                let origin = outs[0];
                const matched = outs.find(
                    (item) =>
                        item.id === connect.case ||
                        (connect.kind && item.kind === connect.kind),
                );
                if (matched) origin = matched;
                const point = worldPoint(event);
                let ghost = svg.querySelector("[data-ghost]");
                if (!ghost) {
                    ghost = document.createElementNS(
                        "http://www.w3.org/2000/svg",
                        "path",
                    );
                    ghost.setAttribute("data-ghost", "1");
                    ghost.setAttribute("class", "wf-edge-path");
                    svg.appendChild(ghost);
                }
                ghost.setAttribute(
                    "d",
                    bezier(origin.x, origin.y, point.x, point.y),
                );
            }
        });
        window.addEventListener("pointerup", (event) => {
            if (panDrag) {
                panDrag = null;
                root.classList.remove("is-panning");
            }
            if (drag) {
                if (drag.moved) {
                    graph.moveNode(drag.id, drag.x, drag.y, true);
                    const loopId = loopAt({ x: drag.x, y: drag.y }, drag.id);
                    const owners = G.bodyOwners(uiState().task);
                    if (loopId) graph.addToLoop(loopId, drag.id);
                    else if (owners[drag.id]) graph.removeFromLoop(drag.id);
                }
                drag = null;
            }
            finishConnect(event);
        });
        root.addEventListener(
            "wheel",
            (event) => {
                event.preventDefault();
                const ui = G.ensureUi(uiState().task);
                const factor = event.deltaY > 0 ? 0.92 : 1.08;
                const zoom = Math.min(1.8, Math.max(0.45, ui.zoom * factor));
                graph.setViewport(zoom, ui.pan);
                applyTransform();
            },
            { passive: false },
        );
        root.addEventListener("dragover", (event) => {
            event.preventDefault();
        });
        root.addEventListener("drop", (event) => {
            event.preventDefault();
            const type = event.dataTransfer.getData(
                "application/x-undefined-node",
            );
            if (!type) return;
            const point = worldPoint(event);
            const { selectedId } = uiState();
            graph.addNode(
                type,
                point,
                selectedId ? { from: selectedId } : { from: "start" },
            );
        });
        window.addEventListener("keydown", (event) => {
            if (event.code === "Space") spaceDown = true;
        });
        window.addEventListener("keyup", (event) => {
            if (event.code === "Space") spaceDown = false;
        });

        graph.subscribe(render);
        render();
        return { render };
    }

    window.WorkflowCanvas = { createCanvas, SWATCH };
})();
