"""B017 — component catalogue /_ui, dev only (spec §5.16)."""

CATALOG_KEYS = [
    "page-header",
    "button",
    "card",
    "field",
    "segmented",
    "check",
    "badge",
    "empty",
    "skeleton",
    "sheet",
    "confirm",
    "toast",
    "progress",
    "avatar",
    "list",
    "secret",
    "icons",
]


def test_ui_catalog_returns_404_by_default(client):
    # Non-regression guard (§11.2 bis): green before the code, by design.
    assert client.get("/_ui").status_code == 404


def test_ui_catalog_flag_defaults_to_false(app_factory, monkeypatch):
    monkeypatch.delenv("UI_CATALOG_ENABLED", raising=False)
    application = app_factory({})
    assert application.config.get("UI_CATALOG_ENABLED") is False


def test_ui_catalog_flag_enabled_from_env(app_factory):
    application = app_factory({"UI_CATALOG_ENABLED": "true"})
    assert application.config.get("UI_CATALOG_ENABLED") is True


def test_ui_catalog_returns_200_when_enabled(app, client):
    app.config["UI_CATALOG_ENABLED"] = True
    assert client.get("/_ui").status_code == 200


def test_ui_catalog_renders_every_component_section(app, client):
    app.config["UI_CATALOG_ENABLED"] = True
    html = client.get("/_ui").data.decode()
    assert [k for k in CATALOG_KEYS if f'data-testid="catalog-{k}"' not in html] == []


def test_ui_catalog_renders_every_icon(app, client):
    from app.icons import ICON_NAMES

    app.config["UI_CATALOG_ENABLED"] = True
    html = client.get("/_ui").data.decode()
    assert [n for n in ICON_NAMES if f'data-icon="{n}"' not in html] == []
