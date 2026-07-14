(function () {
    const ENDPOINT = "/api/v1/management/runtime/weixin";
    const POLL_DELAY_MS = 1800;

    const weixinState = {
        initialized: false,
        loaded: false,
        busy: false,
        status: null,
        pending: [],
        audit: [],
        dialogMode: "bind",
        dialogAlias: "",
        confirmationToken: "",
        sessionId: "",
        pollTimer: null,
        polling: false,
        qrObjectUrl: "",
        qrRevision: 0,
        dialogPreviousFocus: null,
    };

    class WeixinRequestError extends Error {
        constructor(message, response, payload) {
            super(message);
            this.name = "WeixinRequestError";
            this.status = response ? response.status : 0;
            this.payload = payload;
        }
    }

    async function parseJsonSafe(response) {
        try {
            return await response.json();
        } catch (_error) {
            return null;
        }
    }

    function requestMessage(response, payload) {
        if (payload && typeof payload === "object" && payload.error) {
            return String(payload.error);
        }
        return `${response.status} ${response.statusText || "Request failed"}`.trim();
    }

    async function requestJson(path, options = {}) {
        const response = await api(path, options);
        const payload = await parseJsonSafe(response);
        if (!response.ok) {
            throw new WeixinRequestError(
                requestMessage(response, payload),
                response,
                payload,
            );
        }
        return payload && typeof payload === "object" ? payload : {};
    }

    function formatDateTime(value) {
        const text = String(value || "").trim();
        if (!text) return "--";
        const date = new Date(text);
        if (Number.isNaN(date.getTime())) return text;
        return date.toLocaleString();
    }

    function setText(id, value) {
        const element = get(id);
        if (element) element.textContent = String(value);
    }

    function setPageStatus(message, type = "") {
        const status = get("weixinPageStatus");
        if (!status) return;
        status.textContent = message || "";
        status.className = `status-msg ${type}`.trim();
    }

    function setDialogStatus(message, type = "") {
        const status = get("weixinDialogStatus");
        if (!status) return;
        status.textContent = message || "";
        status.className = `status-msg ${type}`.trim();
    }

    function createElement(tag, className = "", text = "") {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text) element.textContent = text;
        return element;
    }

    function runtimeLabel(status) {
        if (!status || !status.enabled) return t("weixin.runtime_disabled");
        if (status.running) return t("weixin.runtime_running");
        return t("weixin.runtime_stopped");
    }

    function renderSummary() {
        const status = weixinState.status || {};
        const accounts = Array.isArray(status.accounts) ? status.accounts : [];
        const connected = accounts.filter(
            (account) => account.connected,
        ).length;
        const runtime = get("weixinRuntimeStatus");
        if (runtime) {
            runtime.textContent = runtimeLabel(status);
            runtime.classList.toggle(
                "is-online",
                Boolean(status.enabled && status.running),
            );
        }
        setText("weixinAccountCount", accounts.length);
        setText("weixinConnectedCount", connected);
        setText("weixinPendingCount", weixinState.pending.length);

        const disabledNotice = get("weixinDisabledNotice");
        if (disabledNotice) {
            disabledNotice.hidden =
                weixinState.status === null || Boolean(status.enabled);
        }
        const bindButton = get("btnWeixinBind");
        if (bindButton) {
            bindButton.disabled =
                weixinState.busy || !status.enabled || !status.running;
        }
    }

    function accountState(account) {
        if (account.connected) {
            return {
                label: t("weixin.state_connected"),
                className: "weixin-state is-connected",
            };
        }
        if (account.error) {
            return {
                label: t("weixin.state_error"),
                className: "weixin-state is-error",
            };
        }
        if (!account.enabled) {
            return {
                label: t("weixin.state_disabled"),
                className: "weixin-state",
            };
        }
        return {
            label: t("weixin.state_offline"),
            className: "weixin-state",
        };
    }

    function makeAccountToggle(account) {
        const label = createElement("label", "toggle-wrapper");
        label.title = account.enabled
            ? t("weixin.disable_account")
            : t("weixin.enable_account");
        const text = createElement(
            "span",
            "sr-only",
            account.enabled
                ? t("weixin.disable_account")
                : t("weixin.enable_account"),
        );
        const input = createElement("input", "toggle-input");
        input.type = "checkbox";
        input.checked = Boolean(account.enabled);
        input.dataset.weixinAction = "toggle";
        input.dataset.alias = String(account.alias || "");
        const track = createElement("span", "toggle-track");
        track.appendChild(createElement("span", "toggle-handle"));
        label.append(text, input, track);
        return label;
    }

    function makeActionButton(label, action, alias, danger = false) {
        const button = createElement(
            "button",
            `btn btn-sm${danger ? " danger" : ""}`,
            label,
        );
        button.type = "button";
        button.dataset.weixinAction = action;
        button.dataset.alias = alias;
        return button;
    }

    function renderAccounts() {
        const body = get("weixinAccountsBody");
        const empty = get("weixinAccountsEmpty");
        if (!body || !empty) return;
        const table = body.closest("table");
        const status = weixinState.status || {};
        const accounts = Array.isArray(status.accounts) ? status.accounts : [];
        body.replaceChildren();
        empty.hidden = accounts.length > 0;
        if (table) table.hidden = accounts.length === 0;

        accounts.forEach((account) => {
            const row = document.createElement("tr");

            const aliasCell = document.createElement("td");
            aliasCell.dataset.label = t("weixin.alias");
            aliasCell.appendChild(
                createElement("code", "", String(account.alias || "--")),
            );

            const identityCell = document.createElement("td");
            identityCell.dataset.label = t("weixin.identity");
            identityCell.appendChild(
                createElement(
                    "code",
                    "",
                    String(account.address || `wechat:${account.qq_id}`),
                ),
            );

            const stateCell = document.createElement("td");
            stateCell.dataset.label = t("weixin.state");
            const view = accountState(account);
            stateCell.appendChild(
                createElement("span", view.className, view.label),
            );
            if (account.error) {
                const error = createElement(
                    "span",
                    "weixin-account-error",
                    String(account.error),
                );
                error.title = String(account.error);
                stateCell.appendChild(error);
            }

            const updatedCell = createElement(
                "td",
                "",
                formatDateTime(account.updated_at),
            );
            updatedCell.dataset.label = t("weixin.updated");

            const actionsCell = createElement("td", "weixin-actions-col");
            actionsCell.dataset.label = t("weixin.actions");
            const actions = createElement("div", "weixin-table-actions");
            actions.append(
                makeAccountToggle(account),
                makeActionButton(
                    t("weixin.rebind"),
                    "rebind",
                    String(account.alias || ""),
                ),
                makeActionButton(
                    t("weixin.unbind"),
                    "delete",
                    String(account.alias || ""),
                    true,
                ),
            );
            actionsCell.appendChild(actions);
            row.append(
                aliasCell,
                identityCell,
                stateCell,
                updatedCell,
                actionsCell,
            );
            body.appendChild(row);
        });
    }

    function renderPending() {
        const container = get("weixinPendingList");
        if (!container) return;
        container.replaceChildren();
        if (!weixinState.pending.length) {
            container.appendChild(
                createElement(
                    "div",
                    "weixin-list-empty",
                    t("weixin.pending_empty"),
                ),
            );
            return;
        }
        weixinState.pending.forEach((item) => {
            const row = createElement("div", "weixin-list-item");
            const main = createElement("div", "weixin-list-main");
            main.appendChild(
                createElement(
                    "span",
                    "weixin-list-title",
                    `${item.account_alias || "--"} · ${t("weixin.unexpected_peer")}`,
                ),
            );
            const meta = createElement("div", "weixin-list-meta");
            meta.append(
                createElement("span", "", `peer ${item.peer_id || "--"}`),
                createElement(
                    "span",
                    "",
                    `${t("weixin.count")} ${item.count || 1}`,
                ),
                createElement("span", "", formatDateTime(item.last_seen_at)),
            );
            main.appendChild(meta);
            const dismiss = createElement(
                "button",
                "btn btn-sm ghost",
                t("weixin.dismiss"),
            );
            dismiss.type = "button";
            dismiss.dataset.weixinAction = "dismiss";
            dismiss.dataset.recordId = String(item.id || "");
            row.append(main, dismiss);
            container.appendChild(row);
        });
    }

    function auditActionLabel(action) {
        const key = `weixin.audit_action_${String(action || "unknown")}`;
        const translated = t(key);
        return translated === key ? String(action || "--") : translated;
    }

    function auditDetails(details) {
        if (!details || typeof details !== "object") return "";
        return Object.entries(details)
            .map(([key, value]) => `${key}=${String(value)}`)
            .join(" · ");
    }

    function renderAudit() {
        const container = get("weixinAuditList");
        if (!container) return;
        container.replaceChildren();
        if (!weixinState.audit.length) {
            container.appendChild(
                createElement(
                    "div",
                    "weixin-list-empty",
                    t("weixin.audit_empty"),
                ),
            );
            return;
        }
        weixinState.audit.forEach((item) => {
            const row = createElement("div", "weixin-list-item");
            const main = createElement("div", "weixin-list-main");
            main.appendChild(
                createElement(
                    "span",
                    "weixin-list-title",
                    auditActionLabel(item.action),
                ),
            );
            const meta = createElement("div", "weixin-list-meta");
            meta.append(
                createElement("span", "", String(item.actor || "system")),
                createElement("span", "", formatDateTime(item.timestamp)),
            );
            const details = auditDetails(item.details);
            if (details) {
                const detail = createElement(
                    "span",
                    "weixin-audit-detail",
                    details,
                );
                detail.title = details;
                meta.appendChild(detail);
            }
            main.appendChild(meta);
            row.appendChild(main);
            container.appendChild(row);
        });
    }

    function render() {
        renderSummary();
        renderAccounts();
        renderPending();
        renderAudit();
    }

    function setBusy(loading) {
        weixinState.busy = Boolean(loading);
        ["btnWeixinRefresh", "btnWeixinBindingSubmit"].forEach((id) => {
            const button = get(id);
            if (button) button.disabled = weixinState.busy;
        });
        renderSummary();
    }

    async function loadAll(force = false) {
        if (weixinState.busy || (!force && weixinState.loaded)) return;
        setBusy(true);
        setPageStatus(t("common.loading"));
        try {
            const [status, pending, audit] = await Promise.all([
                requestJson(ENDPOINT),
                requestJson(`${ENDPOINT}/pending`),
                requestJson(`${ENDPOINT}/audit?limit=50`),
            ]);
            weixinState.status = status;
            weixinState.pending = Array.isArray(pending.items)
                ? pending.items
                : [];
            weixinState.audit = Array.isArray(audit.items) ? audit.items : [];
            weixinState.loaded = true;
            setPageStatus("");
            render();
        } catch (error) {
            setPageStatus(
                error instanceof Error ? error.message : String(error),
                "error",
            );
        } finally {
            setBusy(false);
        }
    }

    function stopPolling() {
        if (weixinState.pollTimer !== null) {
            window.clearTimeout(weixinState.pollTimer);
            weixinState.pollTimer = null;
        }
        weixinState.polling = false;
    }

    function schedulePoll(delay = POLL_DELAY_MS) {
        stopPolling();
        if (!weixinState.sessionId) return;
        weixinState.pollTimer = window.setTimeout(() => {
            pollLogin().catch(() => undefined);
        }, delay);
    }

    function revokeQrObjectUrl() {
        if (!weixinState.qrObjectUrl) return;
        URL.revokeObjectURL(weixinState.qrObjectUrl);
        weixinState.qrObjectUrl = "";
    }

    async function loadQrImage() {
        if (!weixinState.sessionId) return;
        const response = await api(
            `${ENDPOINT}/login/${encodeURIComponent(weixinState.sessionId)}/qr.png?v=${weixinState.qrRevision}`,
        );
        if (!response.ok) {
            const payload = await parseJsonSafe(response);
            throw new WeixinRequestError(
                requestMessage(response, payload),
                response,
                payload,
            );
        }
        const blob = await response.blob();
        revokeQrObjectUrl();
        weixinState.qrObjectUrl = URL.createObjectURL(blob);
        const image = get("weixinQrImage");
        if (image) image.src = weixinState.qrObjectUrl;
    }

    function setQrView(stateKey, message, verify = false) {
        setText("weixinQrState", t(stateKey));
        setText("weixinQrMessage", message || "");
        const verifyForm = get("weixinVerifyForm");
        if (verifyForm) verifyForm.hidden = !verify;
    }

    function schedulePollForStatus(status) {
        return [
            "wait",
            "scaned",
            "scaned_but_redirect",
            "need_verifycode",
        ].includes(status);
    }

    async function pollLogin() {
        if (!weixinState.sessionId || weixinState.polling) return;
        weixinState.polling = true;
        const sessionId = weixinState.sessionId;
        try {
            const payload = await requestJson(
                `${ENDPOINT}/login/${encodeURIComponent(sessionId)}`,
            );
            if (sessionId !== weixinState.sessionId) return;
            const status = String(payload.status || "wait");
            const message = String(payload.message || "");
            if (status === "confirmed") {
                setQrView("weixin.login_confirmed", message);
                stopPolling();
                weixinState.loaded = false;
                await loadAll(true);
                window.setTimeout(() => closeDialog(false), 500);
                return;
            }
            if (status === "need_verifycode") {
                setQrView("weixin.need_verify", message, true);
            } else if (["scaned", "scaned_but_redirect"].includes(status)) {
                setQrView("weixin.scanned", message);
            } else if (status === "expired") {
                setQrView("weixin.qr_expired", message);
            } else if (status === "verify_code_blocked") {
                setQrView("weixin.verify_blocked", message, true);
            } else if (status === "binded_redirect") {
                setQrView("weixin.already_bound", message);
            } else {
                setQrView("weixin.wait_scan", message);
            }
            if (schedulePollForStatus(status)) schedulePoll();
        } catch (error) {
            if (sessionId !== weixinState.sessionId) return;
            setQrView(
                "weixin.poll_failed",
                error instanceof Error ? error.message : String(error),
            );
            if (!(error instanceof WeixinRequestError) || error.status >= 500) {
                schedulePoll(3000);
            }
        } finally {
            weixinState.polling = false;
        }
    }

    function updateDialogLabels() {
        const rebind = weixinState.dialogMode === "rebind";
        setText(
            "weixinDialogTitle",
            t(rebind ? "weixin.dialog_rebind" : "weixin.dialog_bind"),
        );
        setText(
            "btnWeixinBindingSubmit",
            t(
                weixinState.confirmationToken
                    ? "weixin.confirm_continue"
                    : rebind
                      ? "weixin.save_rebind"
                      : "weixin.continue",
            ),
        );
    }

    function showDialog() {
        const backdrop = get("weixinDialogBackdrop");
        const dialog = get("weixinDialog");
        if (!backdrop || !dialog) return;
        weixinState.dialogPreviousFocus = document.activeElement;
        backdrop.hidden = false;
        backdrop.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        trapFocus(dialog);
    }

    function openBindingDialog(mode, account = null) {
        weixinState.dialogMode = mode;
        weixinState.dialogAlias = account ? String(account.alias || "") : "";
        weixinState.confirmationToken = "";
        weixinState.sessionId = "";
        stopPolling();
        revokeQrObjectUrl();

        const bindingForm = get("weixinBindingForm");
        const qrStep = get("weixinQrStep");
        const confirmation = get("weixinConfirmationPanel");
        const aliasInput = get("weixinAliasInput");
        const qqInput = get("weixinQqInput");
        if (bindingForm) bindingForm.hidden = false;
        if (qrStep) qrStep.hidden = true;
        if (confirmation) confirmation.hidden = true;
        if (aliasInput) {
            aliasInput.value = account ? String(account.alias || "") : "";
            aliasInput.readOnly = mode === "rebind";
        }
        if (qqInput) qqInput.value = account ? String(account.qq_id || "") : "";
        setDialogStatus("");
        updateDialogLabels();
        showDialog();
        window.requestAnimationFrame(() => {
            const focusTarget = mode === "rebind" ? qqInput : aliasInput;
            if (focusTarget) focusTarget.focus();
        });
    }

    async function closeDialog(cancelLogin = true) {
        const sessionId = weixinState.sessionId;
        weixinState.sessionId = "";
        stopPolling();
        revokeQrObjectUrl();
        if (cancelLogin && sessionId) {
            try {
                await requestJson(
                    `${ENDPOINT}/login/${encodeURIComponent(sessionId)}`,
                    { method: "DELETE" },
                );
            } catch (_error) {
                // The session may already be confirmed or expired.
            }
        }
        const backdrop = get("weixinDialogBackdrop");
        const dialog = get("weixinDialog");
        if (dialog) releaseFocus(dialog);
        if (backdrop) {
            backdrop.hidden = true;
            backdrop.setAttribute("aria-hidden", "true");
        }
        document.body.style.overflow = "";
        const previousFocus = weixinState.dialogPreviousFocus;
        weixinState.dialogPreviousFocus = null;
        if (previousFocus && typeof previousFocus.focus === "function") {
            previousFocus.focus();
        }
    }

    function showConfirmation(payload) {
        weixinState.confirmationToken = String(
            payload.confirmation_token || "",
        );
        const panel = get("weixinConfirmationPanel");
        if (panel) panel.hidden = false;
        setText("weixinConfirmationText", String(payload.error || ""));
        updateDialogLabels();
    }

    async function submitBinding(event) {
        event.preventDefault();
        if (weixinState.busy) return;
        const alias = String(get("weixinAliasInput")?.value || "").trim();
        const qqId = Number.parseInt(
            String(get("weixinQqInput")?.value || ""),
            10,
        );
        if (!alias || !Number.isSafeInteger(qqId) || qqId <= 0) {
            setDialogStatus(t("weixin.invalid_binding"), "error");
            return;
        }
        const payload = { alias, qq_id: qqId };
        if (weixinState.confirmationToken) {
            payload.confirmation_token = weixinState.confirmationToken;
        }
        setBusy(true);
        setDialogStatus(t("common.loading"));
        try {
            if (weixinState.dialogMode === "rebind") {
                await requestJson(
                    `${ENDPOINT}/accounts/${encodeURIComponent(alias)}`,
                    { method: "PATCH", body: JSON.stringify(payload) },
                );
                setDialogStatus(t("weixin.rebind_saved"), "success");
                weixinState.loaded = false;
                setBusy(false);
                await loadAll(true);
                await closeDialog(false);
                return;
            }
            const result = await requestJson(`${ENDPOINT}/login`, {
                method: "POST",
                body: JSON.stringify(payload),
            });
            weixinState.sessionId = String(result.session_id || "");
            weixinState.qrRevision += 1;
            const form = get("weixinBindingForm");
            const qrStep = get("weixinQrStep");
            if (form) form.hidden = true;
            if (qrStep) qrStep.hidden = false;
            setQrView("weixin.wait_scan", "");
            await loadQrImage();
            schedulePoll(200);
        } catch (error) {
            if (
                error instanceof WeixinRequestError &&
                error.status === 409 &&
                error.payload &&
                error.payload.requires_confirmation
            ) {
                showConfirmation(error.payload);
                setDialogStatus("");
            } else {
                setDialogStatus(
                    error instanceof Error ? error.message : String(error),
                    "error",
                );
            }
        } finally {
            setBusy(false);
        }
    }

    async function refreshQr() {
        if (!weixinState.sessionId || weixinState.busy) return;
        setBusy(true);
        try {
            await requestJson(
                `${ENDPOINT}/login/${encodeURIComponent(weixinState.sessionId)}/refresh`,
                { method: "POST", body: "{}" },
            );
            weixinState.qrRevision += 1;
            await loadQrImage();
            setQrView("weixin.wait_scan", "");
            schedulePoll(200);
        } catch (error) {
            setQrView(
                "weixin.refresh_failed",
                error instanceof Error ? error.message : String(error),
            );
        } finally {
            setBusy(false);
        }
    }

    async function submitVerifyCode(event) {
        event.preventDefault();
        if (!weixinState.sessionId || weixinState.busy) return;
        const input = get("weixinVerifyInput");
        const code = String(input?.value || "").trim();
        if (!code) return;
        setBusy(true);
        try {
            await requestJson(
                `${ENDPOINT}/login/${encodeURIComponent(weixinState.sessionId)}/verify`,
                { method: "POST", body: JSON.stringify({ code }) },
            );
            if (input) input.value = "";
            setQrView("weixin.verify_submitted", "");
            schedulePoll(200);
        } catch (error) {
            setQrView(
                "weixin.verify_failed",
                error instanceof Error ? error.message : String(error),
                true,
            );
        } finally {
            setBusy(false);
        }
    }

    function findAccount(alias) {
        const accounts = Array.isArray(weixinState.status?.accounts)
            ? weixinState.status.accounts
            : [];
        return accounts.find((account) => account.alias === alias) || null;
    }

    async function toggleAccount(input) {
        const alias = String(input.dataset.alias || "");
        const enabled = Boolean(input.checked);
        input.disabled = true;
        try {
            await requestJson(
                `${ENDPOINT}/accounts/${encodeURIComponent(alias)}`,
                {
                    method: "PATCH",
                    body: JSON.stringify({ enabled }),
                },
            );
            weixinState.loaded = false;
            await loadAll(true);
            showToast(
                enabled
                    ? t("weixin.account_enabled")
                    : t("weixin.account_disabled"),
                "success",
            );
        } catch (error) {
            input.checked = !enabled;
            showToast(
                error instanceof Error ? error.message : String(error),
                "error",
            );
        } finally {
            input.disabled = false;
        }
    }

    async function deleteAccount(alias) {
        if (!window.confirm(t("weixin.confirm_unbind"))) return;
        try {
            await requestJson(
                `${ENDPOINT}/accounts/${encodeURIComponent(alias)}`,
                { method: "DELETE" },
            );
            weixinState.loaded = false;
            await loadAll(true);
            showToast(t("weixin.unbound"), "success");
        } catch (error) {
            showToast(
                error instanceof Error ? error.message : String(error),
                "error",
            );
        }
    }

    async function dismissPending(recordId) {
        try {
            await requestJson(
                `${ENDPOINT}/pending/${encodeURIComponent(recordId)}`,
                { method: "DELETE" },
            );
            weixinState.loaded = false;
            await loadAll(true);
        } catch (error) {
            showToast(
                error instanceof Error ? error.message : String(error),
                "error",
            );
        }
    }

    function handleAccountAction(event) {
        const target = event.target.closest("[data-weixin-action]");
        if (!target) return;
        const action = target.dataset.weixinAction;
        const alias = String(target.dataset.alias || "");
        if (action === "rebind") {
            const account = findAccount(alias);
            if (account) openBindingDialog("rebind", account);
        } else if (action === "delete") {
            deleteAccount(alias);
        } else if (action === "dismiss") {
            dismissPending(String(target.dataset.recordId || ""));
        }
    }

    function init() {
        if (weixinState.initialized) return;
        weixinState.initialized = true;
        get("btnWeixinRefresh")?.addEventListener("click", () => loadAll(true));
        get("btnWeixinBind")?.addEventListener("click", () =>
            openBindingDialog("bind"),
        );
        get("weixinBindingForm")?.addEventListener("submit", submitBinding);
        get("weixinVerifyForm")?.addEventListener("submit", submitVerifyCode);
        get("btnWeixinQrRefresh")?.addEventListener("click", refreshQr);
        [
            "btnWeixinDialogClose",
            "btnWeixinBindingCancel",
            "btnWeixinQrCancel",
        ].forEach((id) => {
            get(id)?.addEventListener("click", () => closeDialog(true));
        });
        get("weixinAccountsBody")?.addEventListener(
            "click",
            handleAccountAction,
        );
        get("weixinPendingList")?.addEventListener(
            "click",
            handleAccountAction,
        );
        get("weixinAccountsBody")?.addEventListener("change", (event) => {
            const target = event.target;
            if (
                target instanceof HTMLInputElement &&
                target.dataset.weixinAction === "toggle"
            ) {
                toggleAccount(target);
            }
        });
        get("weixinDialogBackdrop")?.addEventListener(
            "pointerdown",
            (event) => {
                if (event.target === event.currentTarget) closeDialog(true);
            },
        );
        document.addEventListener("keydown", (event) => {
            if (
                event.key === "Escape" &&
                !get("weixinDialogBackdrop")?.hidden
            ) {
                closeDialog(true);
            }
        });
    }

    function onTabActivated(tab) {
        if (tab === "weixin") {
            loadAll(false);
        }
    }

    function onLanguageChanged() {
        if (weixinState.loaded) render();
        if (!get("weixinDialogBackdrop")?.hidden) updateDialogLabels();
    }

    window.WeixinController = {
        init,
        loadAll,
        onTabActivated,
        onLanguageChanged,
    };
})();
