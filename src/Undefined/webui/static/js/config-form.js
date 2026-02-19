async function loadConfig() {
    if (state.configLoading) return;
    state.configLoading = true;
    state.configLoaded = false;
    setConfigState("loading");
    try {
        const res = await api("/api/config/summary");
        const data = await res.json();
        state.config = data.data;
        state.comments = data.comments || {};
        state.configLoaded = true;
        buildConfigForm();
        setConfigState(null);
    } catch (e) {
        setConfigState("error");
        showToast(t("config.error"), "error", 5000);
    } finally {
        state.configLoading = false;
    }
}

function getComment(path) {
    const entry = state.comments && state.comments[path];
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[state.lang] || entry.en || entry.zh || "";
}

function updateCommentTexts() {
    document.querySelectorAll("[data-comment-path]").forEach(el => {
        const path = el.getAttribute("data-comment-path");
        if (path) el.innerText = getComment(path);
    });
}

function updateConfigSearchIndex() {
    document.querySelectorAll(".form-group").forEach(group => {
        const label = group.querySelector(".form-label");
        const hint = group.querySelector(".form-hint");
        const path = group.dataset.path || "";
        group.dataset.searchText = `${path} ${label ? label.innerText : ""} ${hint ? hint.innerText : ""}`.toLowerCase();
    });
}

function buildConfigForm() {
    const container = get("formSections");
    if (!container) return;
    container.textContent = "";

    for (const [section, values] of Object.entries(state.config)) {
        if (typeof values !== "object" || Array.isArray(values)) continue;

        const card = document.createElement("div");
        card.className = "card config-card";
        card.dataset.section = section;
        const collapsed = !!state.configCollapsed[section];
        card.classList.toggle("is-collapsed", collapsed);

        const header = document.createElement("div");
        header.className = "config-card-header";

        const title = document.createElement("h3");
        title.className = "form-section-title";
        title.textContent = section;
        header.appendChild(title);

        const actions = document.createElement("div");
        actions.className = "config-card-actions";

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "btn ghost btn-sm";
        toggle.dataset.section = section;
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
        toggle.addEventListener("click", () => toggleSection(section));
        actions.appendChild(toggle);

        header.appendChild(actions);
        card.appendChild(header);

        const sectionComment = getComment(section);
        if (sectionComment) {
            const hint = document.createElement("p");
            hint.className = "form-section-hint";
            hint.innerText = sectionComment;
            hint.dataset.commentPath = section;
            card.appendChild(hint);
        }

        const fieldGrid = document.createElement("div");
        fieldGrid.className = "form-fields";
        card.appendChild(fieldGrid);

        for (const [key, val] of Object.entries(values)) {
            if (typeof val === "object" && !Array.isArray(val)) {
                const subSection = document.createElement("div");
                subSection.className = "form-subsection";

                const subTitle = document.createElement("div");
                subTitle.className = "form-subtitle";
                subTitle.innerText = `[${section}.${key}]`;
                subSection.appendChild(subTitle);

                const subCommentKey = `${section}.${key}`;
                const subComment = getComment(subCommentKey);
                if (subComment) {
                    const subHint = document.createElement("div");
                    subHint.className = "form-subtitle-hint";
                    subHint.innerText = subComment;
                    subHint.dataset.commentPath = subCommentKey;
                    subSection.appendChild(subHint);
                }

                const subGrid = document.createElement("div");
                subGrid.className = "form-fields";
                for (const [sk, sv] of Object.entries(val)) {
                    const subPath = `${section}.${key}.${sk}`;
                    if (sv !== null && typeof sv === "object" && !Array.isArray(sv)) {
                        subGrid.appendChild(createSubSubSection(subPath, sv));
                    } else if (Array.isArray(sv) && (AOT_PATHS.has(subPath) || sv.some(i => typeof i === "object" && i !== null))) {
                        subGrid.appendChild(createAotWidget(subPath, sv));
                    } else {
                        subGrid.appendChild(createField(subPath, sv));
                    }
                }
                subSection.appendChild(subGrid);
                fieldGrid.appendChild(subSection);
                continue;
            }
            fieldGrid.appendChild(createField(`${section}.${key}`, val));
        }
        container.appendChild(card);
    }

    updateConfigSearchIndex();
    applyConfigFilter();
}

function toggleSection(section) {
    state.configCollapsed[section] = !state.configCollapsed[section];
    document.querySelectorAll(".config-card").forEach(card => {
        if (card.dataset.section !== section) return;
        const collapsed = !!state.configCollapsed[section];
        card.classList.toggle("is-collapsed", collapsed);
        const toggle = card.querySelector(".config-card-actions button");
        if (toggle) {
            toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
            toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        }
    });
}

function setAllSectionsCollapsed(collapsed) {
    document.querySelectorAll(".config-card").forEach(card => {
        const section = card.dataset.section;
        if (!section) return;
        state.configCollapsed[section] = collapsed;
        card.classList.toggle("is-collapsed", collapsed);
        const toggle = card.querySelector(".config-card-actions button");
        if (toggle) {
            toggle.innerText = collapsed ? t("config.expand_section") : t("config.collapse_section");
            toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
        }
    });
}

function applyConfigFilter() {
    if (!state.configLoaded) return;
    const query = state.configSearch.trim().toLowerCase();
    let matchCount = 0;
    document.querySelectorAll(".config-card").forEach(card => {
        let cardMatches = 0;
        card.querySelectorAll(".form-group").forEach(group => {
            const isMatch = !query || (group.dataset.searchText || "").includes(query);
            group.classList.toggle("is-hidden", !isMatch);
            group.classList.toggle("is-match", isMatch && query.length > 0);
            if (isMatch) cardMatches += 1;
        });
        card.querySelectorAll(".form-subsection").forEach(section => {
            section.style.display = section.querySelector(".form-group:not(.is-hidden)") ? "" : "none";
        });
        card.classList.toggle("force-open", query.length > 0);
        card.classList.toggle("is-hidden", query.length > 0 && cardMatches === 0);
        matchCount += cardMatches;
    });
    if (query.length > 0 && matchCount === 0) {
        setConfigState("empty");
    } else if (state.configLoaded) {
        setConfigState(null);
    }
}

function showSaveStatus(status, text) {
    const el = get("saveStatus");
    const txt = get("saveStatusText");
    state.saveStatus = status;
    if (status === "saving") {
        el.style.opacity = "1";
        el.classList.add("active");
        txt.innerText = text || t("config.saving");
    } else if (status === "saved") {
        el.classList.remove("active");
        txt.innerText = text || t("config.saved");
        setTimeout(() => {
            if (!state.saveTimer) { el.style.opacity = "0"; state.saveStatus = "idle"; updateSaveStatusText(); }
        }, 2000);
    } else if (status === "error") {
        el.classList.remove("active");
        txt.innerText = text || t("config.save_error");
        el.style.opacity = "1";
    }
}

function isSensitiveKey(path) {
    return /(password|token|secret|api_key|apikey|access_key|private_key)/i.test(path);
}

function isLongText(value) {
    return typeof value === "string" && (value.length > 80 || value.includes("\n"));
}

function createField(path, val) {
    const group = document.createElement("div");
    group.className = "form-group";
    group.dataset.path = path;

    const label = document.createElement("label");
    label.className = "form-label";
    label.innerText = path.split(".").pop();
    group.appendChild(label);

    const comment = getComment(path);
    if (comment) {
        const hint = document.createElement("div");
        hint.className = "form-hint";
        hint.innerText = comment;
        hint.dataset.commentPath = path;
        group.appendChild(hint);
    }

    group.dataset.searchText = `${path} ${comment || ""}`.toLowerCase();

    let input;
    if (typeof val === "boolean") {
        const wrapper = document.createElement("label");
        wrapper.className = "toggle-wrapper";
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.className = "toggle-input config-input";
        toggle.dataset.path = path;
        toggle.dataset.valueType = "boolean";
        toggle.checked = Boolean(val);
        const track = document.createElement("span");
        track.className = "toggle-track";
        const handle = document.createElement("span");
        handle.className = "toggle-handle";
        track.appendChild(handle);
        wrapper.appendChild(toggle);
        wrapper.appendChild(track);
        group.appendChild(wrapper);
        input = toggle;
        input.onchange = () => autoSave();
    } else {
        const isArray = Array.isArray(val);
        const isNumber = typeof val === "number";
        const isSecret = isSensitiveKey(path);

        if (isLongText(val)) {
            input = document.createElement("textarea");
            input.className = "form-control form-textarea config-input";
            input.value = val || "";
            input.dataset.valueType = "string";
        } else {
            input = document.createElement("input");
            input.className = "form-control config-input";
            if (isNumber) {
                input.type = "number";
                input.step = "any";
                input.value = String(val);
                input.dataset.valueType = "number";
            } else if (isArray) {
                input.type = "text";
                input.value = val.join(", ");
                input.dataset.valueType = "array";
                input.dataset.arrayType = val.every(item => typeof item === "number") ? "number" : "string";
            } else {
                input.type = isSecret ? "password" : "text";
                input.value = val == null ? "" : String(val);
                input.dataset.valueType = "string";
                if (isSecret) input.setAttribute("autocomplete", "new-password");
            }
        }

        input.dataset.path = path;
        group.appendChild(input);
        input.oninput = () => {
            if (state.saveTimer) clearTimeout(state.saveTimer);
            showSaveStatus("saving", t("config.typing"));
            state.saveTimer = setTimeout(() => { state.saveTimer = null; autoSave(); }, 1000);
        };
    }
    return group;
}

const AOT_PATHS = new Set(["models.chat.pool.models", "models.agent.pool.models"]);

function createSubSubSection(path, obj) {
    const div = document.createElement("div");
    div.className = "form-subsection";
    const title = document.createElement("div");
    title.className = "form-subtitle";
    title.innerText = `[${path}]`;
    div.appendChild(title);
    const comment = getComment(path);
    if (comment) {
        const hint = document.createElement("div");
        hint.className = "form-subtitle-hint";
        hint.innerText = comment;
        hint.dataset.commentPath = path;
        div.appendChild(hint);
    }
    const grid = document.createElement("div");
    grid.className = "form-fields";
    for (const [k, v] of Object.entries(obj)) {
        const subPath = `${path}.${k}`;
        if (AOT_PATHS.has(subPath) || (Array.isArray(v) && v.length > 0 && v.every(i => typeof i === "object" && i !== null))) {
            grid.appendChild(createAotWidget(subPath, v));
        } else {
            grid.appendChild(createField(subPath, v));
        }
    }
    div.appendChild(grid);
    return div;
}

function createAotEntry(path, entry) {
    const div = document.createElement("div");
    div.className = "aot-entry";
    div.style.cssText = "border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;";
    const fields = document.createElement("div");
    fields.className = "form-fields";
    for (const [k, v] of Object.entries(entry)) {
        const fg = document.createElement("div");
        fg.className = "form-group";
        fg.dataset.path = `${path}[].${k}`;
        const lbl = document.createElement("label");
        lbl.className = "form-label";
        lbl.innerText = k;
        fg.appendChild(lbl);
        const isSecret = isSensitiveKey(k);
        const inp = document.createElement("input");
        inp.className = "form-control aot-field-input";
        inp.type = isSecret ? "password" : "text";
        inp.value = v == null ? "" : String(v);
        inp.dataset.fieldKey = k;
        if (isSecret) inp.setAttribute("autocomplete", "new-password");
        inp.oninput = () => {
            if (state.saveTimer) clearTimeout(state.saveTimer);
            showSaveStatus("saving", t("config.typing"));
            state.saveTimer = setTimeout(() => { state.saveTimer = null; autoSave(); }, 1000);
        };
        fg.appendChild(inp);
        fields.appendChild(fg);
    }
    div.appendChild(fields);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn ghost btn-sm";
    removeBtn.innerText = t("config.aot_remove");
    removeBtn.onclick = () => { div.remove(); autoSave(); };
    div.appendChild(removeBtn);
    return div;
}

function createAotWidget(path, arr) {
    const DEFAULT_ENTRY = { model_name: "", api_url: "", api_key: "" };
    const container = document.createElement("div");
    container.className = "form-group";
    container.dataset.path = path;
    const lbl = document.createElement("div");
    lbl.className = "form-label";
    lbl.innerText = path.split(".").pop();
    container.appendChild(lbl);
    const comment = getComment(path);
    if (comment) {
        const hint = document.createElement("div");
        hint.className = "form-hint";
        hint.innerText = comment;
        hint.dataset.commentPath = path;
        container.appendChild(hint);
    }
    const entriesDiv = document.createElement("div");
    entriesDiv.dataset.aotPath = path;
    container.appendChild(entriesDiv);
    (arr || []).forEach(entry => entriesDiv.appendChild(createAotEntry(path, entry)));
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn ghost btn-sm";
    addBtn.style.marginTop = "4px";
    addBtn.innerText = t("config.aot_add");
    addBtn.onclick = () => {
        const template = arr && arr.length > 0 ? Object.fromEntries(Object.keys(arr[0]).map(k => [k, ""])) : DEFAULT_ENTRY;
        entriesDiv.appendChild(createAotEntry(path, template));
        autoSave();
    };
    container.appendChild(addBtn);
    return container;
}

async function autoSave() {
    showSaveStatus("saving");

    const patch = {};
    document.querySelectorAll(".config-input").forEach(input => {
        const path = input.dataset.path;
        let val;
        if (input.type === "checkbox") {
            val = input.checked;
        } else {
            const raw = input.value;
            const valueType = input.dataset.valueType || "string";
            if (valueType === "number") {
                const trimmed = raw.trim();
                if (!trimmed) { val = ""; }
                else {
                    val = trimmed.includes(".") ? parseFloat(trimmed) : parseInt(trimmed, 10);
                    if (Number.isNaN(val)) val = raw;
                }
            } else if (valueType === "array") {
                const items = raw.split(",").map(s => s.trim()).filter(Boolean);
                val = input.dataset.arrayType === "number"
                    ? items.map(item => { const num = Number(item); return Number.isNaN(num) ? item : num; })
                    : items;
            } else {
                val = raw;
            }
        }
        patch[path] = val;
    });

    document.querySelectorAll("[data-aot-path]").forEach(container => {
        const aotPath = container.dataset.aotPath;
        const entries = [];
        container.querySelectorAll(".aot-entry").forEach(entry => {
            const obj = {};
            entry.querySelectorAll(".aot-field-input").forEach(inp => { obj[inp.dataset.fieldKey] = inp.value; });
            entries.push(obj);
        });
        patch[aotPath] = entries;
    });

    try {
        const res = await api("/api/patch", { method: "POST", body: JSON.stringify({ patch }) });
        const data = await res.json();
        if (data.success) {
            showSaveStatus("saved");
            if (data.warning) showToast(`${t("common.warning")}: ${data.warning}`, "warning", 5000);
        } else {
            showSaveStatus("error", t("config.save_error"));
            showToast(`${t("common.error")}: ${data.error}`, "error", 5000);
        }
    } catch (e) {
        showSaveStatus("error", t("config.save_network_error"));
        showToast(`${t("common.error")}: ${e.message}`, "error", 5000);
    }
}

async function resetConfig() {
    if (!confirm(t("config.reset_confirm"))) return;
    try {
        await loadConfig();
        showToast(t("config.reload_success"), "info");
    } catch (e) {
        showToast(t("config.reload_error"), "error");
    }
}
