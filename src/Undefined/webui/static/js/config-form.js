let configFormLayoutInitialized = false;
let configLayoutResizeObserver = null;

function getConfigStickyChromeElements() {
    return [
        document.querySelector("#tab-config > .header.sticky"),
        document.querySelector(".mobile-topbar"),
    ].filter(Boolean);
}

function updateConfigSectionStickyOffset() {
    const form = get("formSections");
    if (!form) return;

    const stickyHeight = getConfigStickyChromeElements().reduce(
        (height, element) => {
            const styles = window.getComputedStyle(element);
            if (
                styles.display === "none" ||
                !["fixed", "sticky"].includes(styles.position)
            ) {
                return height;
            }
            const elementHeight = element.getBoundingClientRect().height;
            const containingBlock = element.parentElement;
            if (
                styles.position === "sticky" &&
                containingBlock &&
                containingBlock.getBoundingClientRect().height <=
                    elementHeight + 1
            ) {
                return height;
            }
            return Math.max(height, elementHeight);
        },
        0,
    );
    form.style.setProperty(
        "--config-section-sticky-offset",
        `${Math.ceil(stickyHeight)}px`,
    );
}

function initConfigFormLayout() {
    if (configFormLayoutInitialized) return;
    configFormLayoutInitialized = true;

    const chromeElements = getConfigStickyChromeElements();
    if ("ResizeObserver" in window) {
        configLayoutResizeObserver = new ResizeObserver(() =>
            updateConfigSectionStickyOffset(),
        );
        chromeElements.forEach((element) =>
            configLayoutResizeObserver.observe(element),
        );
    }
    window.addEventListener("resize", updateConfigSectionStickyOffset);
    window.requestAnimationFrame(updateConfigSectionStickyOffset);
}

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
    document.querySelectorAll("[data-comment-path]").forEach((el) => {
        const path = el.getAttribute("data-comment-path");
        if (path) el.innerText = getComment(path);
    });
}

function updateConfigSearchIndex() {
    // Only index real config fields (data-path). Nested structural
    // form-groups inside request_params editors (key/type) must not
    // participate, or search will hide them independently of the parent.
    document.querySelectorAll(".form-group[data-path]").forEach((group) => {
        const label = group.querySelector(":scope > .form-label");
        const hint = group.querySelector(":scope > .form-hint");
        const path = group.dataset.path || "";
        group.dataset.searchText =
            `${path} ${label ? label.innerText : ""} ${hint ? hint.innerText : ""}`.toLowerCase();
    });
}

function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isAotCollection(path, value) {
    return (
        Array.isArray(value) &&
        (AOT_PATHS.has(path) ||
            value.some((item) => item !== null && typeof item === "object"))
    );
}

function isRequestParamsPath(path) {
    return path === "request_params" || path.endsWith(".request_params");
}

function scheduleAutoSave() {
    if (state.saveTimer) clearTimeout(state.saveTimer);
    showSaveStatus("saving", t("config.typing"));
    state.saveTimer = setTimeout(() => {
        state.saveTimer = null;
        autoSave();
    }, 1000);
}

function createEditorNode(path, value) {
    if (isRequestParamsPath(path)) {
        return createRequestParamsWidget(
            path,
            isPlainObject(value) ? value : {},
        );
    }
    if (isPlainObject(value)) {
        return createSubSubSection(path, value);
    }
    if (isAotCollection(path, value)) {
        return createAotWidget(path, value);
    }
    return createField(path, value);
}

function buildConfigForm() {
    const container = get("formSections");
    if (!container) return;
    container.textContent = "";

    let sectionIndex = 0;
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
        toggle.className = "btn ghost btn-sm config-section-toggle";
        toggle.dataset.section = section;
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");

        const toggleIcon = document.createElement("span");
        toggleIcon.className = "config-section-toggle-icon";
        toggleIcon.setAttribute("aria-hidden", "true");
        toggle.appendChild(toggleIcon);

        const toggleLabel = document.createElement("span");
        toggleLabel.className = "config-section-toggle-label";
        toggleLabel.innerText = collapsed
            ? t("config.expand_section")
            : t("config.collapse_section");
        toggle.appendChild(toggleLabel);
        toggle.addEventListener("click", () => toggleSection(section));
        actions.appendChild(toggle);

        header.appendChild(actions);
        card.appendChild(header);

        const body = document.createElement("div");
        body.className = "config-card-body";
        body.id = `config-section-body-${sectionIndex}`;
        toggle.setAttribute("aria-controls", body.id);
        sectionIndex += 1;

        const sectionComment = getComment(section);
        if (sectionComment) {
            const hint = document.createElement("p");
            hint.className = "form-section-hint";
            hint.innerText = sectionComment;
            hint.dataset.commentPath = section;
            body.appendChild(hint);
        }

        const fieldGrid = document.createElement("div");
        fieldGrid.className = "form-fields";
        body.appendChild(fieldGrid);

        for (const [key, val] of Object.entries(values)) {
            fieldGrid.appendChild(createEditorNode(`${section}.${key}`, val));
        }
        card.appendChild(body);
        container.appendChild(card);
    }

    updateConfigSearchIndex();
    applyConfigFilter();
    updateConfigSectionStickyOffset();
}

function isConfigSearchActive() {
    return state.configSearch.trim().length > 0;
}

function syncConfigSearchMode(searchActive) {
    if (state.configSearchModeActive === searchActive) return;
    state.configSearchModeActive = searchActive;
    state.configSearchCollapsed = {};
}

function updateConfigSectionPresentations() {
    const searchActive = isConfigSearchActive();
    document.querySelectorAll(".config-card").forEach((card) => {
        const section = card.dataset.section;
        if (!section) return;

        const collapsed = searchActive
            ? !!state.configSearchCollapsed[section]
            : !!state.configCollapsed[section];
        card.classList.toggle("is-collapsed", collapsed);

        const toggle = card.querySelector(".config-section-toggle");
        if (!toggle) return;
        const label = toggle.querySelector(".config-section-toggle-label");
        if (label) {
            label.innerText = collapsed
                ? t("config.expand_section")
                : t("config.collapse_section");
        }
        toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    });
}

function preserveConfigViewportAnchor(anchor, update) {
    const beforeTop = anchor?.getBoundingClientRect().top;
    update();
    if (!anchor || !anchor.isConnected || !Number.isFinite(beforeTop)) return;

    const afterTop = anchor.getBoundingClientRect().top;
    const delta = afterTop - beforeTop;
    if (Math.abs(delta) < 0.5) return;
    window.scrollBy({ top: delta, left: 0, behavior: "auto" });
}

function findConfigViewportAnchor() {
    const form = get("formSections");
    if (!form) return null;
    const rawOffset = window
        .getComputedStyle(form)
        .getPropertyValue("--config-section-sticky-offset");
    const stickyOffset = Number.parseFloat(rawOffset) || 0;
    let firstVisible = null;

    for (const header of document.querySelectorAll(".config-card-header")) {
        const card = header.closest(".config-card");
        if (!card || card.classList.contains("is-hidden")) continue;
        const headerRect = header.getBoundingClientRect();
        const cardRect = card.getBoundingClientRect();
        if (cardRect.bottom <= stickyOffset || headerRect.top >= innerHeight) {
            continue;
        }
        if (
            headerRect.top <= stickyOffset + 1 &&
            cardRect.bottom > stickyOffset
        ) {
            return header;
        }
        if (!firstVisible && headerRect.bottom > stickyOffset) {
            firstVisible = header;
        }
    }
    return firstVisible;
}

function toggleSection(section) {
    const card = Array.from(document.querySelectorAll(".config-card")).find(
        (candidate) => candidate.dataset.section === section,
    );
    const anchor = card?.querySelector(".config-card-header") || null;
    preserveConfigViewportAnchor(anchor, () => {
        const collapseState = isConfigSearchActive()
            ? state.configSearchCollapsed
            : state.configCollapsed;
        collapseState[section] = !collapseState[section];
        updateConfigSectionPresentations();
    });
}

function setAllSectionsCollapsed(collapsed) {
    const searchActive = isConfigSearchActive();
    const anchor = findConfigViewportAnchor();
    preserveConfigViewportAnchor(anchor, () => {
        const collapseState = searchActive
            ? state.configSearchCollapsed
            : state.configCollapsed;
        document.querySelectorAll(".config-card").forEach((card) => {
            const section = card.dataset.section;
            if (
                section &&
                (!searchActive || !card.classList.contains("is-hidden"))
            ) {
                collapseState[section] = collapsed;
            }
        });
        updateConfigSectionPresentations();
    });
}

function applyConfigFilter() {
    if (!state.configLoaded) return;
    const query = state.configSearch.trim().toLowerCase();
    syncConfigSearchMode(query.length > 0);
    let matchCount = 0;
    document.querySelectorAll(".config-card").forEach((card) => {
        let cardMatches = 0;
        // Only filter top-level config fields. Nested form-groups inside
        // structured editors (request_params key/type) have no data-path
        // and must stay visible whenever their parent field is shown.
        card.querySelectorAll(".form-group[data-path]").forEach((group) => {
            const isMatch =
                !query || (group.dataset.searchText || "").includes(query);
            group.classList.toggle("is-hidden", !isMatch);
            group.classList.toggle("is-match", isMatch && query.length > 0);
            if (isMatch) cardMatches += 1;
        });
        card.querySelectorAll(".form-subsection").forEach((section) => {
            section.style.display = section.querySelector(
                ".form-group[data-path]:not(.is-hidden)",
            )
                ? ""
                : "none";
        });
        card.classList.toggle(
            "is-hidden",
            query.length > 0 && cardMatches === 0,
        );
        matchCount += cardMatches;
    });
    updateConfigSectionPresentations();
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
            if (!state.saveTimer) {
                el.style.opacity = "0";
                state.saveStatus = "idle";
                updateSaveStatusText();
            }
        }, 2000);
    } else if (status === "error") {
        el.classList.remove("active");
        txt.innerText = text || t("config.save_error");
        el.style.opacity = "1";
    }
}

function isSensitiveKey(path) {
    return /(password|token|secret|api_key|apikey|access_key|private_key)/i.test(
        path,
    );
}

function isLongText(value) {
    return (
        typeof value === "string" && (value.length > 80 || value.includes("\n"))
    );
}

const FIELD_SELECT_EMPTY_OPTION = {
    value: "",
    label: "（空 / 不传，使用默认）",
};

const FIELD_SELECT_OPTION_RULES = [
    {
        match: (path) => path.endsWith(".pool.strategy"),
        options: ["default", "round_robin", "random"],
    },
    {
        match: (path) => path === "message_batcher.strategy",
        options: ["extend", "fixed"],
    },
];

/** @type {Record<string, Array<string | { value: string, label: string }>>} */
const FIELD_SELECT_OPTIONS = {
    api_mode: [
        "openai.chat_completions",
        "openai.responses",
        "anthropic.messages",
    ],
    mode: ["off", "blacklist", "allowlist"],
    agent_call_message_enabled: ["none", "agent", "tools", "clean", "all"],
    level: ["DEBUG", "INFO", "WARNING", "ERROR"],
    archive_prune_mode: ["delete", "merge", "none"],
    oversize_strategy: ["downgrade", "info"],
    prefer_quality: ["80", "64", "32"],
    default_archive_format: ["zip", "tar.gz"],
    tool_invoke_expose: [
        "tools",
        "toolsets",
        "tools+toolsets",
        "agents",
        "all",
    ],
    query_default_mode: ["keyword", "semantic", "hybrid"],
    gif_analysis_mode: ["grid", "multi"],
    provider: ["xingzhige", "models"],
    xingzhige_size: ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
    openai_quality: [FIELD_SELECT_EMPTY_OPTION, "standard", "hd"],
    openai_style: [FIELD_SELECT_EMPTY_OPTION, "vivid", "natural"],
    openai_size: [
        FIELD_SELECT_EMPTY_OPTION,
        "1024x1024",
        "1280x720",
        "720x1280",
        "1792x1024",
        "1024x1792",
    ],
    // path -> options key mapping (underscore-separated segments)
    image_gen_provider: ["xingzhige", "models"],
};

function normalizeSelectOption(option) {
    if (typeof option === "string") {
        return { value: option, label: option };
    }
    return {
        value: String(option.value ?? ""),
        label: String(option.label ?? option.value ?? ""),
    };
}

function populateSelectInput(select, options, currentValue) {
    const current = currentValue == null ? "" : String(currentValue);
    const normalized = options.map(normalizeSelectOption);
    const seen = new Set(normalized.map((item) => item.value));
    if (current && !seen.has(current)) {
        normalized.unshift({
            value: current,
            label: `${current} (当前值)`,
        });
    }
    for (const { value, label } of normalized) {
        const option = document.createElement("option");
        option.value = value;
        option.innerText = label || value || "（空）";
        option.selected = current === value;
        select.appendChild(option);
    }
}

function getSelectValueType(options) {
    const values = options
        .map(normalizeSelectOption)
        .map((item) => item.value)
        .filter((value) => value !== "");
    if (values.length === 0) {
        return "string";
    }
    const allNumeric = values.every((value) =>
        /^-?\d+(?:\.\d+)?$/.test(value.trim()),
    );
    return allNumeric ? "number" : "string";
}

function getFieldSelectOptions(path) {
    for (const rule of FIELD_SELECT_OPTION_RULES) {
        if (rule.match(path)) {
            return rule.options;
        }
    }
    // 先用完整路径的下划线拼接形式（支持嵌套路径如 image_gen.provider）
    const underscoreKey = path.replace(/\./g, "_");
    if (FIELD_SELECT_OPTIONS[underscoreKey]) {
        return FIELD_SELECT_OPTIONS[underscoreKey];
    }
    // 回退到最后一个 key（兼容顶字段如 api_mode）
    const key = path.split(".").pop();
    return FIELD_SELECT_OPTIONS[key] || null;
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
        const selectOptions = getFieldSelectOptions(path);

        if (selectOptions) {
            input = document.createElement("select");
            input.className = "form-control config-input";
            input.dataset.valueType = getSelectValueType(selectOptions);
            populateSelectInput(input, selectOptions, val);
        } else if (isLongText(val)) {
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
                input.dataset.arrayType = val.every(
                    (item) => typeof item === "number",
                )
                    ? "number"
                    : "string";
            } else {
                input.type = isSecret ? "password" : "text";
                input.value = val == null ? "" : String(val);
                input.dataset.valueType = "string";
                if (isSecret)
                    input.setAttribute("autocomplete", "new-password");
            }
        }

        input.dataset.path = path;
        group.appendChild(input);
        if (selectOptions) {
            input.onchange = () => autoSave();
        } else {
            input.oninput = () => scheduleAutoSave();
        }
    }
    return group;
}

const AOT_PATHS = new Set([
    "models.chat.pool.models",
    "models.agent.pool.models",
]);

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
        grid.appendChild(createEditorNode(subPath, v));
    }
    div.appendChild(grid);
    return div;
}

function buildEmptyStructuredValue(value) {
    if (Array.isArray(value)) {
        return value.length > 0 ? [buildEmptyStructuredValue(value[0])] : [];
    }
    if (isPlainObject(value)) {
        return Object.fromEntries(
            Object.keys(value).map((key) => [
                key,
                buildEmptyStructuredValue(value[key]),
            ]),
        );
    }
    if (typeof value === "boolean") return false;
    if (value === null) return null;
    return "";
}

function inferStructuredType(value) {
    if (Array.isArray(value)) return "array";
    if (isPlainObject(value)) return "object";
    return "scalar";
}

function inferScalarType(value) {
    if (value === null) return "null";
    if (typeof value === "number") return "number";
    if (typeof value === "boolean") return "boolean";
    return "string";
}

function createRequestParamsWidget(path, value) {
    const group = document.createElement("div");
    group.className = "form-group config-request-params";
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
    const editor = createStructuredValueEditor(value, { rootType: "object" });
    editor.dataset.requestParamsRoot = "true";
    group.appendChild(editor);
    return group;
}

function createStructuredActionButton(text, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn ghost btn-sm";
    button.innerText = text;
    button.onclick = onClick;
    return button;
}

function createStructuredValueEditor(value, options = {}) {
    const rootType = options.rootType || inferStructuredType(value);
    if (rootType === "object") {
        return createStructuredObjectEditor(isPlainObject(value) ? value : {});
    }
    if (rootType === "array") {
        return createStructuredArrayEditor(Array.isArray(value) ? value : []);
    }
    return createStructuredScalarEditor(value);
}

function createStructuredObjectEditor(value) {
    const wrapper = document.createElement("div");
    wrapper.dataset.structuredType = "object";

    const body = document.createElement("div");
    body.className = "request-params-object-body";
    wrapper.appendChild(body);

    Object.entries(value).forEach(([key, itemValue]) => {
        body.appendChild(createStructuredObjectEntry(key, itemValue));
    });

    const actions = document.createElement("div");
    actions.style.marginTop = "8px";
    actions.style.display = "flex";
    actions.style.gap = "8px";
    actions.style.flexWrap = "wrap";
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Field`, () => {
            body.appendChild(createStructuredObjectEntry("", ""));
            autoSave();
        }),
    );
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Object`, () => {
            body.appendChild(createStructuredObjectEntry("", {}));
            autoSave();
        }),
    );
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Array`, () => {
            body.appendChild(createStructuredObjectEntry("", []));
            autoSave();
        }),
    );
    wrapper.appendChild(actions);

    return wrapper;
}

function createStructuredObjectEntry(key, value) {
    const entry = document.createElement("div");
    entry.className = "request-params-object-entry";
    entry.style.cssText =
        "border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;";

    const keyGroup = document.createElement("div");
    keyGroup.className = "form-group";
    const keyLabel = document.createElement("label");
    keyLabel.className = "form-label";
    keyLabel.innerText = "key";
    keyGroup.appendChild(keyLabel);
    const keyInput = document.createElement("input");
    keyInput.type = "text";
    keyInput.className = "form-control request-params-key-input";
    keyInput.value = key || "";
    keyInput.oninput = () => scheduleAutoSave();
    keyGroup.appendChild(keyInput);
    entry.appendChild(keyGroup);

    const valueContainer = document.createElement("div");
    valueContainer.className = "request-params-entry-value";
    valueContainer.appendChild(createStructuredValueEditor(value));
    entry.appendChild(valueContainer);

    const removeBtn = createStructuredActionButton(
        t("config.aot_remove"),
        () => {
            entry.remove();
            autoSave();
        },
    );
    entry.appendChild(removeBtn);

    return entry;
}

function createStructuredArrayEditor(value) {
    const wrapper = document.createElement("div");
    wrapper.dataset.structuredType = "array";

    const body = document.createElement("div");
    body.className = "request-params-array-body";
    wrapper.appendChild(body);

    value.forEach((itemValue) => {
        body.appendChild(createStructuredArrayEntry(itemValue));
    });

    const actions = document.createElement("div");
    actions.style.marginTop = "8px";
    actions.style.display = "flex";
    actions.style.gap = "8px";
    actions.style.flexWrap = "wrap";
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Value`, () => {
            body.appendChild(createStructuredArrayEntry(""));
            autoSave();
        }),
    );
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Object`, () => {
            body.appendChild(createStructuredArrayEntry({}));
            autoSave();
        }),
    );
    actions.appendChild(
        createStructuredActionButton(`${t("config.aot_add")} Array`, () => {
            body.appendChild(createStructuredArrayEntry([]));
            autoSave();
        }),
    );
    wrapper.appendChild(actions);

    return wrapper;
}

function createStructuredArrayEntry(value) {
    const entry = document.createElement("div");
    entry.className = "request-params-array-entry";
    entry.style.cssText =
        "border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;";

    const valueContainer = document.createElement("div");
    valueContainer.className = "request-params-entry-value";
    valueContainer.appendChild(createStructuredValueEditor(value));
    entry.appendChild(valueContainer);

    const removeBtn = createStructuredActionButton(
        t("config.aot_remove"),
        () => {
            entry.remove();
            autoSave();
        },
    );
    entry.appendChild(removeBtn);

    return entry;
}

function createStructuredScalarEditor(value) {
    const wrapper = document.createElement("div");
    wrapper.dataset.structuredType = "scalar";

    const typeGroup = document.createElement("div");
    typeGroup.className = "form-group";
    const typeLabel = document.createElement("label");
    typeLabel.className = "form-label";
    typeLabel.innerText = "type";
    typeGroup.appendChild(typeLabel);

    const typeSelect = document.createElement("select");
    typeSelect.className = "form-control request-params-scalar-type";
    ["string", "number", "boolean", "null"].forEach((type) => {
        const option = document.createElement("option");
        option.value = type;
        option.innerText = type;
        typeSelect.appendChild(option);
    });
    typeSelect.value = inferScalarType(value);
    typeGroup.appendChild(typeSelect);
    wrapper.appendChild(typeGroup);

    const valueContainer = document.createElement("div");
    valueContainer.className = "request-params-scalar-value";
    wrapper.appendChild(valueContainer);

    const renderValueInput = () => {
        const scalarType = typeSelect.value;
        valueContainer.textContent = "";

        if (scalarType === "null") {
            const emptyHint = document.createElement("div");
            emptyHint.className = "form-hint";
            emptyHint.innerText = "null";
            valueContainer.appendChild(emptyHint);
            return;
        }

        if (scalarType === "boolean") {
            const booleanWrap = document.createElement("label");
            booleanWrap.className = "toggle-wrapper";
            const booleanInput = document.createElement("input");
            booleanInput.type = "checkbox";
            booleanInput.className = "toggle-input request-params-scalar-input";
            booleanInput.checked = typeof value === "boolean" ? value : false;
            booleanInput.onchange = () => autoSave();
            const track = document.createElement("span");
            track.className = "toggle-track";
            const handle = document.createElement("span");
            handle.className = "toggle-handle";
            track.appendChild(handle);
            booleanWrap.appendChild(booleanInput);
            booleanWrap.appendChild(track);
            valueContainer.appendChild(booleanWrap);
            return;
        }

        const input = document.createElement("input");
        input.className = "form-control request-params-scalar-input";
        input.type = scalarType === "number" ? "number" : "text";
        if (scalarType === "number") {
            input.step = "any";
            input.value = typeof value === "number" ? String(value) : "";
        } else {
            input.value = value == null ? "" : String(value);
        }
        input.oninput = () => scheduleAutoSave();
        valueContainer.appendChild(input);
    };

    typeSelect.onchange = () => {
        value =
            typeSelect.value === "boolean"
                ? false
                : typeSelect.value === "null"
                  ? null
                  : "";
        renderValueInput();
        autoSave();
    };

    renderValueInput();
    return wrapper;
}

function getStructuredValueChild(container) {
    return Array.from(container.children).find(
        (child) => child.dataset && child.dataset.structuredType,
    );
}

function readStructuredValueEditor(node) {
    const type = node.dataset.structuredType;
    if (type === "object") {
        const result = {};
        const body = node.querySelector(".request-params-object-body");
        Array.from(body ? body.children : []).forEach((entry) => {
            const keyInput = entry.querySelector(".request-params-key-input");
            const key = keyInput ? keyInput.value.trim() : "";
            if (!key) return;
            const valueContainer = entry.querySelector(
                ".request-params-entry-value",
            );
            const valueNode = valueContainer
                ? getStructuredValueChild(valueContainer)
                : null;
            if (!valueNode) return;
            result[key] = readStructuredValueEditor(valueNode);
        });
        return result;
    }
    if (type === "array") {
        const body = node.querySelector(".request-params-array-body");
        return Array.from(body ? body.children : []).map((entry) => {
            const valueContainer = entry.querySelector(
                ".request-params-entry-value",
            );
            const valueNode = valueContainer
                ? getStructuredValueChild(valueContainer)
                : null;
            return valueNode ? readStructuredValueEditor(valueNode) : null;
        });
    }

    const scalarType =
        node.querySelector(".request-params-scalar-type")?.value || "string";
    if (scalarType === "null") return null;
    const scalarInput = node.querySelector(".request-params-scalar-input");
    if (scalarType === "boolean") {
        return Boolean(scalarInput?.checked);
    }
    const raw = scalarInput ? scalarInput.value : "";
    if (scalarType === "number") {
        const parsed = Number(raw);
        return Number.isNaN(parsed) ? 0 : parsed;
    }
    return raw;
}

function createAotScalarInput(key, value) {
    const isLong = isLongText(value);
    const isNumber = typeof value === "number";
    const isBoolean = typeof value === "boolean";
    const isArray = Array.isArray(value);
    const isSecret = isSensitiveKey(key);

    if (isBoolean) {
        const wrapper = document.createElement("label");
        wrapper.className = "toggle-wrapper";
        const toggle = document.createElement("input");
        toggle.type = "checkbox";
        toggle.className = "toggle-input aot-field-input";
        toggle.dataset.valueType = "boolean";
        toggle.checked = Boolean(value);
        toggle.onchange = () => autoSave();
        const track = document.createElement("span");
        track.className = "toggle-track";
        const handle = document.createElement("span");
        handle.className = "toggle-handle";
        track.appendChild(handle);
        wrapper.appendChild(toggle);
        wrapper.appendChild(track);
        return wrapper;
    }

    let input;
    if (isLong) {
        input = document.createElement("textarea");
        input.className = "form-control form-textarea aot-field-input";
    } else {
        input = document.createElement("input");
        input.className = "form-control aot-field-input";
        input.type = isNumber ? "number" : isSecret ? "password" : "text";
        if (isNumber) input.step = "any";
        if (isSecret) input.setAttribute("autocomplete", "new-password");
    }

    input.dataset.valueType = isNumber
        ? "number"
        : isArray
          ? "array"
          : "string";
    if (isArray) {
        input.dataset.arrayType = value.every(
            (item) => typeof item === "number",
        )
            ? "number"
            : "string";
        input.value = value.join(", ");
    } else {
        input.value = value == null ? "" : String(value);
    }
    input.oninput = () => scheduleAutoSave();
    return input;
}

function createAotEntry(path, entry) {
    const div = document.createElement("div");
    div.className = "aot-entry";
    div.style.cssText =
        "border:1px solid var(--border);border-radius:6px;padding:10px;margin-bottom:8px;";
    const fields = document.createElement("div");
    fields.className = "form-fields";

    for (const [key, value] of Object.entries(entry)) {
        const field = document.createElement("div");
        field.className = "form-group aot-entry-field";
        field.dataset.fieldKey = key;
        field.dataset.path = `${path}[].${key}`;

        const label = document.createElement("label");
        label.className = "form-label";
        label.innerText = key;
        field.appendChild(label);

        const fieldPath = `${path}.${key}`;
        if (isPlainObject(value) || Array.isArray(value)) {
            field.dataset.fieldEditor = "structured";
            const editor = createStructuredValueEditor(value, {
                rootType: isRequestParamsPath(fieldPath)
                    ? "object"
                    : inferStructuredType(value),
            });
            field.appendChild(editor);
        } else {
            field.dataset.fieldEditor = "scalar";
            field.appendChild(createAotScalarInput(key, value));
        }
        fields.appendChild(field);
    }

    div.appendChild(fields);
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn ghost btn-sm";
    removeBtn.innerText = t("config.aot_remove");
    removeBtn.onclick = () => {
        div.remove();
        autoSave();
    };
    div.appendChild(removeBtn);
    return div;
}

const MODEL_POOL_ENTRY_DEFAULTS = {
    model_name: "",
    api_url: "",
    api_key: "",
    api_mode: "openai.chat_completions",
    max_tokens: 4096,
    use_proxy: false,
    context_window_tokens: 8192,
    queue_interval_seconds: 1.0,
    thinking_enabled: false,
    thinking_budget_tokens: 0,
    thinking_include_budget: true,
    thinking_tool_call_compat: true,
    reasoning_content_replay: true,
    system_prompt_as_user: false,
    responses_tool_choice_compat: false,
    responses_force_stateless_replay: false,
    prompt_cache_enabled: true,
    reasoning_enabled: false,
    reasoning_effort: "medium",
    stream_enabled: false,
    request_params: {},
};

function buildAotTemplate(path, arr) {
    if (arr && arr.length > 0) {
        const template = buildEmptyStructuredValue(arr[0]);
        if (AOT_PATHS.has(path)) {
            for (const [key, value] of Object.entries(
                MODEL_POOL_ENTRY_DEFAULTS,
            )) {
                if (!Object.prototype.hasOwnProperty.call(template, key)) {
                    template[key] = isPlainObject(value) ? {} : value;
                }
            }
        }
        return template;
    }
    return {
        ...MODEL_POOL_ENTRY_DEFAULTS,
        request_params: {},
    };
}

function createAotWidget(path, arr) {
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
    container.dataset.searchText = `${path} ${comment || ""}`.toLowerCase();
    const entriesDiv = document.createElement("div");
    entriesDiv.dataset.aotPath = path;
    container.appendChild(entriesDiv);
    (arr || []).forEach((entry) =>
        entriesDiv.appendChild(createAotEntry(path, entry)),
    );
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "btn ghost btn-sm";
    addBtn.style.marginTop = "4px";
    addBtn.innerText = t("config.aot_add");
    addBtn.onclick = () => {
        entriesDiv.appendChild(
            createAotEntry(path, buildAotTemplate(path, arr)),
        );
        autoSave();
    };
    container.appendChild(addBtn);
    return container;
}

function parseInputValue(input) {
    const valueType = input.dataset.valueType || "string";
    if (valueType === "boolean") {
        return input.checked;
    }
    const raw = input.value;
    if (valueType === "number") {
        const trimmed = raw.trim();
        if (!trimmed) return "";
        const parsed = trimmed.includes(".")
            ? parseFloat(trimmed)
            : parseInt(trimmed, 10);
        return Number.isNaN(parsed) ? raw : parsed;
    }
    if (valueType === "array") {
        const items = raw
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
        return input.dataset.arrayType === "number"
            ? items.map((item) => {
                  const number = Number(item);
                  return Number.isNaN(number) ? item : number;
              })
            : items;
    }
    return raw;
}

async function autoSave() {
    showSaveStatus("saving");

    const patch = {};
    document.querySelectorAll(".config-input").forEach((input) => {
        patch[input.dataset.path] = parseInputValue(input);
    });

    document
        .querySelectorAll("[data-request-params-root]")
        .forEach((editor) => {
            const group = editor.closest(".form-group");
            if (!group?.dataset.path) return;
            patch[group.dataset.path] = readStructuredValueEditor(editor);
        });

    document.querySelectorAll("[data-aot-path]").forEach((container) => {
        const aotPath = container.dataset.aotPath;
        const entries = [];
        container.querySelectorAll(".aot-entry").forEach((entry) => {
            const obj = {};
            entry.querySelectorAll(".aot-entry-field").forEach((field) => {
                const key = field.dataset.fieldKey;
                if (!key) return;
                if (field.dataset.fieldEditor === "structured") {
                    const valueNode = getStructuredValueChild(field);
                    obj[key] = valueNode
                        ? readStructuredValueEditor(valueNode)
                        : {};
                    return;
                }
                const input = field.querySelector(".aot-field-input");
                if (!input) return;
                obj[key] = parseInputValue(input);
            });
            entries.push(obj);
        });
        patch[aotPath] = entries;
    });

    try {
        const res = await api("/api/patch", {
            method: "POST",
            body: JSON.stringify({ patch }),
        });
        const data = await res.json();
        if (data.success) {
            showSaveStatus("saved");
            if (data.warning)
                showToast(
                    `${t("common.warning")}: ${data.warning}`,
                    "warning",
                    5000,
                );
        } else {
            showSaveStatus("error", t("config.save_error"));
            showToast(`${t("common.error")}: ${data.error}`, "error", 5000);
        }
    } catch (e) {
        showSaveStatus("error", t("config.save_network_error"));
        showToast(`${t("common.error")}: ${e.message}`, "error", 5000);
    }
}

async function syncConfigTemplate(button) {
    if (!confirm(t("config.sync_confirm"))) return;
    setButtonLoading(button, true);
    showSaveStatus("saving", t("config.syncing"));
    try {
        const previewRes = await api("/api/config/sync-template?write=false", {
            method: "POST",
        });
        const previewData = await previewRes.json();
        if (!previewData.success) {
            showSaveStatus("error", t("config.save_error"));
            showToast(
                `${t("common.error")}: ${previewData.error || t("config.sync_error")}`,
                "error",
                5000,
            );
            return;
        }

        let shouldPrune = false;
        if (
            Array.isArray(previewData.removed_paths) &&
            previewData.removed_paths.length > 0
        ) {
            const listing = previewData.removed_paths
                .map((p) => `  - ${p}`)
                .join("\n");
            shouldPrune = confirm(
                `${t("config.prune_confirm")}\n\n${listing}\n\n${t("config.prune_confirm_action")}`,
            );
        }

        const finalUrl = shouldPrune
            ? "/api/config/sync-template?prune=true"
            : "/api/config/sync-template";
        const finalRes = await api(finalUrl, { method: "POST" });
        const finalData = await finalRes.json();
        if (!finalData.success) {
            showSaveStatus("error", t("config.save_error"));
            showToast(
                `${t("common.error")}: ${finalData.error || t("config.sync_error")}`,
                "error",
                5000,
            );
            return;
        }

        await loadConfig();
        showSaveStatus("saved", t("config.saved"));
        if (finalData.warning) {
            showToast(
                `${t("common.warning")}: ${finalData.warning}`,
                "warning",
                5000,
            );
        }
        if (shouldPrune) {
            const removedCount = Number.isFinite(finalData.removed_count)
                ? finalData.removed_count
                : Array.isArray(finalData.removed_paths)
                  ? finalData.removed_paths.length
                  : 0;
            showToast(
                `${t("config.prune_success")} (-${removedCount})`,
                "info",
                4000,
            );
        } else {
            const suffix = Number.isFinite(finalData.added_count)
                ? ` (+${finalData.added_count})`
                : "";
            showToast(`${t("config.sync_success")}${suffix}`, "info", 4000);
        }
    } catch (e) {
        showSaveStatus("error", t("config.sync_error"));
        showToast(`${t("common.error")}: ${e.message}`, "error", 5000);
    } finally {
        setButtonLoading(button, false);
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
