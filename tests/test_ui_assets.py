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










def test_static_css_dir_no_longer_contains_main_css():
    assert not (REPO / "app/static/css/main.css").exists()


# --- Fingerprints --------------------------------------------------------------








# --- Icons -----------------------------------------------------------------------












# --- Macros ---------------------------------------------------------------------














