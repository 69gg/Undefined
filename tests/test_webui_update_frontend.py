from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from pathlib import Path

from Undefined.utils import io as async_io


_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _ElementParentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, str | None]] = []
        self.parent_tags_by_id: dict[str, tuple[str, ...]] = {}
        self.parent_ids_by_id: dict[str, tuple[str, ...]] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        element_id = dict(attrs).get("id")
        if element_id is not None:
            self.parent_tags_by_id[element_id] = tuple(
                parent_tag for parent_tag, _parent_id in self._stack
            )
            self.parent_ids_by_id[element_id] = tuple(
                parent_id
                for _parent_tag, parent_id in self._stack
                if parent_id is not None
            )
        if tag not in _VOID_ELEMENTS:
            self._stack.append((tag, element_id))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return


def _read(path: str) -> str:
    content = asyncio.run(async_io.read_text(Path(path)))
    assert content is not None
    return content


def test_update_dialog_has_accessible_structure_and_actions() -> None:
    html = _read("src/Undefined/webui/templates/index.html")

    assert 'id="updateDialogBackdrop"' in html
    assert 'id="updateDialog"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert 'aria-labelledby="updateDialogTitle"' in html
    assert 'id="updateDialogCancel"' in html
    assert 'id="updateDialogConfirm"' in html
    assert 'data-i18n="update.check"' in html


def test_update_dialog_is_outside_hidden_app_view() -> None:
    html = _read("src/Undefined/webui/templates/index.html")
    parser = _ElementParentParser()
    parser.feed(html)

    assert parser.parent_tags_by_id["updateDialogBackdrop"] == ("html", "body")
    assert "view-app" not in parser.parent_ids_by_id["updateDialogBackdrop"]


def test_update_frontend_checks_once_automatically_and_allows_manual_check() -> None:
    bot_js = _read("src/Undefined/webui/static/js/bot.js")
    main_js = _read("src/Undefined/webui/static/js/main.js")
    auth_js = _read("src/Undefined/webui/static/js/auth.js")

    assert "async function checkForUpdates" in bot_js
    assert "state.updateCheckStarted" in bot_js
    assert '"/api/update-check"' in bot_js
    assert '"/api/update-check?manual=true"' in bot_js
    assert "function openUpdateDialog" in bot_js
    assert "trapFocus(dialog)" in bot_js
    assert "releaseFocus(dialog)" in bot_js
    assert "target_version: targetVersion" in bot_js
    assert "checkForUpdates({ manual: true" in main_js
    assert "if (state.authenticated) void checkForUpdates()" in main_js
    assert "void checkForUpdates()" in auth_js


def test_update_dialog_only_links_https_releases() -> None:
    bot_js = _read("src/Undefined/webui/static/js/bot.js")

    assert 'releaseUrl.startsWith("https://")' in bot_js
    assert 'releaseLink.removeAttribute("href")' in bot_js
    assert "releaseLink.hidden = true" in bot_js


def test_update_dialog_has_mobile_and_reduced_motion_compatible_styles() -> None:
    components_css = _read("src/Undefined/webui/static/css/components.css")
    responsive_css = _read("src/Undefined/webui/static/css/responsive.css")

    assert ".update-dialog-backdrop[hidden]" in components_css
    assert ".update-version-flow" in components_css
    assert "@media (max-width: 480px)" in components_css
    assert ".update-dialog-actions .btn" in components_css
    assert "overflow-wrap: anywhere" in components_css
    assert "prefers-reduced-motion: reduce" in responsive_css


def test_update_i18n_covers_actions_and_ineligible_reasons() -> None:
    i18n = _read("src/Undefined/webui/static/js/i18n.js")

    for key in (
        "update.check",
        "update.dialog_title",
        "update.pull_restart",
        "update.up_to_date",
        "update.reason.branch_mismatch",
        "update.reason.dirty_worktree",
        "update.reason.release_not_fast_forward",
    ):
        assert i18n.count(f'"{key}"') == 2


def test_startup_entrypoints_no_longer_apply_updates() -> None:
    main_source = _read("src/Undefined/main.py")
    webui_source = _read("src/Undefined/webui/app.py")

    assert "apply_git_update" not in main_source
    assert "apply_git_release_update" not in main_source
    assert "apply_git_update" not in webui_source
    assert "apply_git_release_update" not in webui_source
