async function login(pwd, statusId, buttonId) {
    const s = get(statusId);
    const button = buttonId ? get(buttonId) : null;
    s.innerText = t("auth.signing_in");
    setButtonLoading(button, true);
    try {
        const res = await api("/api/login", {
            method: "POST",
            body: JSON.stringify({ password: pwd })
        });
        const data = await res.json();
        if (data.success) {
            state.authenticated = true;
            await checkSession();
            refreshUI();
            s.innerText = "";
        } else {
            if (data.code === "default_password") {
                s.innerText = t("auth.change_required");
                showToast(t("auth.change_required"), "warning", 5000);
            } else {
                s.innerText = data.error || t("auth.login_failed");
            }
        }
    } catch (e) {
        s.innerText = e.message || t("auth.login_failed");
    } finally {
        setButtonLoading(button, false);
    }
}

async function changePassword(currentId, newId, statusId, buttonId) {
    const statusEl = get(statusId);
    const button = buttonId ? get(buttonId) : null;
    const currentEl = get(currentId);
    const newEl = get(newId);
    const currentPassword = currentEl ? currentEl.value.trim() : "";
    const newPassword = newEl ? newEl.value.trim() : "";

    if (!currentPassword || !newPassword || currentPassword === newPassword) {
        if (statusEl) statusEl.innerText = t("auth.password_update_failed");
        return;
    }

    if (statusEl) statusEl.innerText = t("common.loading");
    setButtonLoading(button, true);
    try {
        const res = await api("/api/password", {
            method: "POST",
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        const data = await res.json();
        if (data.success) {
            if (statusEl) statusEl.innerText = t("auth.password_updated_login");
            showToast(t("auth.password_updated_login"), "success", 4000);
            if (currentEl) currentEl.value = "";
            if (newEl) newEl.value = "";
            state.usingDefaultPassword = false;
            await login(newPassword, statusId, buttonId);
        } else {
            const msg = data.code === "local_required"
                ? t("auth.password_change_local")
                : (data.error || t("auth.password_update_failed"));
            if (statusEl) statusEl.innerText = msg;
            showToast(msg, "error", 5000);
        }
    } catch (e) {
        const msg = e.message || t("auth.password_update_failed");
        if (statusEl) statusEl.innerText = msg;
        showToast(`${t("auth.password_update_failed")}: ${msg}`, "error", 5000);
    } finally {
        setButtonLoading(button, false);
    }
}

async function checkSession() {
    try {
        const res = await api("/api/session");
        const data = await res.json();
        state.authenticated = data.authenticated;
        state.usingDefaultPassword = !!data.using_default_password;
        const warning = get("warningBox");
        if (warning) warning.style.display = data.using_default_password ? "block" : "none";
        const navFooter = get("navFooter");
        if (navFooter) navFooter.innerText = data.summary || "";
        updateAuthPanels();
        return data;
    } catch (e) {
        return { authenticated: false };
    }
}
