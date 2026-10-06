"""B017 — Tailwind build, design tokens, asset fingerprints, icons, macros (spec §2, §3, §5, §6, §8.2)."""

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMPILED_CSS = REPO / "app/static/css/app.css"

COMPONENT_CLASSES = [
    "ui-btn",
    "ui-btn--primary",
    "ui-btn--secondary",
    "ui-btn--ghost",
    "ui-btn--danger",
    "ui-btn--sm",
    "ui-btn--lg",
    "ui-btn--icon",
    "ui-btn--block",
    "ui-card",
    "ui-card--link",
    "ui-card__link",
    "ui-card__action",
    "ui-card__title",
    "ui-field",
    "ui-label",
    "ui-label__optional",
    "ui-input",
    "ui-select",
    "ui-textarea",
    "ui-help",
    "ui-error",
    "ui-segmented",
    "ui-segmented__option",
    "ui-check",
    "ui-radio",
    "ui-switch",
    "ui-badge",
    "ui-badge--neutral",
    "ui-badge--primary",
    "ui-badge--success",
    "ui-badge--warning",
    "ui-badge--danger",
    "ui-badge--info",
    "ui-empty",
    "ui-skeleton",
    "ui-sheet",
    "ui-sheet--dialog",
    "ui-sheet__panel",
    "ui-sheet__header",
    "ui-sheet__title",
    "ui-sheet__body",
    "ui-toast-region",
    "ui-toast",
    "ui-progress",
    "ui-avatar",
    "ui-list",
    "ui-list__item",
    "ui-list__link",
    "ui-icon",
    "ui-page-header",
    "ui-link",
    "ui-skip-link",
    "ui-tab",
    "ui-bottom-nav",
    "ui-sidebar",
    "ui-menu",
    "ui-menu__item",
    "ui-menu__heading",
    "ui-identity",
    "ui-offline",
    "ui-form",
    "ui-form--inline",
    "ui-toast-stack",
    "ui-dialog-actions",
]

SPEC_ICON_NAMES = [
    # navigation
    "house",
    "calendar-days",
    "utensils",
    "list-checks",
    "wallet",
    "ellipsis",
    "vote",
    "info",
    "message-circle",
    "image",
    "users",
    "scroll-text",
    "user-plus",
    "shield-check",
    "calendar-plus",
    "calendar-range",
    # header
    "sun",
    "moon",
    "globe",
    "log-out",
    "log-in",
    "user",
    "arrow-left",
    # actions
    "plus",
    "x",
    "check",
    "pencil",
    "trash-2",
    "copy",
    "share-2",
    "link",
    "eye",
    "eye-off",
    "download",
    "upload",
    "camera",
    "qr-code",
    "mail",
    "send",
    "search",
    "funnel",
    "ellipsis-vertical",
    "chevron-down",
    "chevron-up",
    "chevron-left",
    "chevron-right",
    "grip-vertical",
    "move",
    "arrow-left-right",
    "refresh-cw",
    "external-link",
    "map-pin",
    "clock",
    "shopping-cart",
    "bell",
    "bell-off",
    "settings",
    "lock",
    "key-round",
    "sunset",
    "euro",
    "undo-2",
    "archive",
    # states
    "circle-check",
    "circle-alert",
    "triangle-alert",
    "loader-circle",
    "wifi-off",
    "circle-question-mark",
    "inbox",
    "sparkles",
]


def _css() -> str:
    return COMPILED_CSS.read_text(encoding="utf-8")


def _ui_macros(app):
    return app.jinja_env.get_template("_components/ui.html").module


# --- Build -------------------------------------------------------------------


def test_package_json_pins_tailwind_versions():
    package = json.loads((REPO / "package.json").read_text(encoding="utf-8"))
    assert package["devDependencies"] == {"@tailwindcss/cli": "4.3.3", "tailwindcss": "4.3.3"}


def test_source_css_imports_legacy_into_legacy_layer():
    source = (REPO / "app/static/src/app.css").read_text(encoding="utf-8")
    assert '@import "./legacy.css" layer(legacy);' in source


def test_compiled_css_layers_appear_in_order():
    css = _css()
    positions = []
    for layer in ("legacy", "theme", "base", "components", "utilities"):
        match = re.search(rf"@layer {layer}\b", css)
        positions.append(match.start() if match else -1)
    assert -1 not in positions
    assert positions == sorted(set(positions))


def test_compiled_css_defines_dark_theme_tokens():
    assert re.search(r'\[data-theme=("?)dark\1\]\{[^}]*--color-canvas:#171512', _css())


def test_compiled_css_contains_all_component_classes():
    css = _css()
    assert [c for c in COMPONENT_CLASSES if f".{c}" not in css] == []


def test_compiled_css_has_no_default_tailwind_palette():
    assert "--color-red-500" not in _css()


def test_static_css_dir_no_longer_contains_main_css():
    assert not (REPO / "app/static/css/main.css").exists()


# --- Fingerprints --------------------------------------------------------------


def test_asset_url_appends_content_hash(app):
    from app.ui import asset_url

    digest = hashlib.sha256(COMPILED_CSS.read_bytes()).hexdigest()[:10]
    with app.test_request_context():
        assert asset_url("css/app.css") == "/static/css/app.css?v=" + digest


def test_asset_url_changes_when_file_content_changes(app, monkeypatch, tmp_path):
    from app.ui import asset_url

    monkeypatch.setattr(app, "static_folder", str(tmp_path))
    target = tmp_path / "a.css"
    target.write_text("a{color:red}", encoding="utf-8")
    with app.test_request_context():
        url1 = asset_url("a.css")
        target.write_text("a{color:blue}", encoding="utf-8")
        stat = target.stat()
        os.utime(target, (stat.st_atime + 1, stat.st_mtime + 1))
        url2 = asset_url("a.css")
    assert url1 != url2


def test_asset_url_raises_for_missing_file(app):
    from app.ui import asset_url

    with app.test_request_context(), pytest.raises(FileNotFoundError):
        asset_url("css/absent.css")


# --- Icons -----------------------------------------------------------------------


def test_icon_renders_decorative_svg_by_default():
    from app.ui import icon

    assert 'aria-hidden="true"' in str(icon("house"))


def test_icon_with_label_renders_img_role():
    from app.ui import icon

    assert 'role="img" aria-label="Fermer"' in str(icon("x", label="Fermer"))


def test_icon_unknown_name_raises_key_error():
    from app.ui import icon

    with pytest.raises(KeyError):
        icon("inconnue")


def test_icon_set_matches_specified_names():
    from app.icons import ICON_NAMES

    assert list(ICON_NAMES) == SPEC_ICON_NAMES


def test_icon_label_is_html_escaped():
    from app.ui import icon

    assert 'aria-label="&lt;b&gt;"' in str(icon("x", label="<b>"))


# --- Macros ---------------------------------------------------------------------


def test_field_macro_links_help_and_error_with_describedby(app):
    with app.test_request_context():
        out = str(_ui_macros(app).field("title", "Titre", help="Aide", error="Erreur"))
    assert 'aria-describedby="f-title-help f-title-error"' in out


def test_field_macro_sets_aria_invalid_when_error(app):
    with app.test_request_context():
        out = str(_ui_macros(app).field("title", "Titre", help="Aide", error="Erreur"))
    assert 'aria-invalid="true"' in out


def test_field_macro_omits_describedby_without_help_or_error(app):
    with app.test_request_context():
        out = str(_ui_macros(app).field("title", "Titre"))
    assert "aria-describedby" not in out


def test_field_macro_label_targets_input_id(app):
    with app.test_request_context():
        out = str(_ui_macros(app).field("title", "Titre"))
    assert '<label class="ui-label" for="f-title">' in out
    assert 'id="f-title"' in out


def test_field_macro_marks_optional_field(app):
    with app.test_request_context():
        out = str(_ui_macros(app).field("title", "Titre"))
    assert "(facultatif)" in out


def test_sheet_macro_renders_labelled_dialog(app):
    source = (
        '{% from "_components/ui.html" import sheet %}'
        '{% call sheet("demo", "Titre") %}x{% endcall %}'
    )
    with app.test_request_context():
        out = app.jinja_env.from_string(source).render()
    assert 'aria-labelledby="demo-title"' in out


def test_empty_state_macro_renders_title(app):
    with app.test_request_context():
        out = str(_ui_macros(app).empty_state("inbox", "Rien ici"))
    assert '<p class="ui-empty__title">Rien ici</p>' in out
