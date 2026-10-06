"""B017 — root service worker, offline page, manifest (spec §8)."""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _manifest() -> dict:
    return json.loads((REPO / "app/static/manifest.json").read_text(encoding="utf-8"))


# --- /sw.js ------------------------------------------------------------------------


def test_sw_route_returns_200(client):
    assert client.get("/sw.js").status_code == 200


def test_sw_route_has_javascript_mimetype(client):
    assert client.get("/sw.js").mimetype == "application/javascript"


def test_sw_route_has_no_cache_header(client):
    assert client.get("/sw.js").headers.get("Cache-Control") == "no-cache"


def test_sw_route_allows_root_scope(client):
    assert client.get("/sw.js").headers.get("Service-Worker-Allowed") == "/"


def test_sw_cache_name_derived_from_asset_version(app, client):
    from app.ui import asset_version

    body = client.get("/sw.js").data.decode()
    with app.test_request_context():
        expected = f'"holishared-{asset_version()}"'
    assert expected in body


def test_asset_version_changes_when_an_asset_hash_changes(app, monkeypatch):
    from app import ui as app_ui

    with app.test_request_context():
        monkeypatch.setattr(app_ui, "asset_hash", lambda filename: "a" * 10)
        version_a = app_ui.asset_version()
        monkeypatch.setattr(app_ui, "asset_hash", lambda filename: "b" * 10)
        version_b = app_ui.asset_version()
    assert version_a != version_b


def test_sw_precaches_fingerprinted_app_css(app, client):
    from app.ui import asset_url

    body = client.get("/sw.js").data.decode()
    with app.test_request_context():
        expected = asset_url("css/app.css")
    assert expected in body


def test_sw_precaches_offline_page(client):
    assert '"/offline"' in client.get("/sw.js").data.decode()


def test_sw_does_not_precache_alpine(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "alpine" not in resp.data.decode()


def test_sw_handles_skip_waiting_message(client):
    assert "SKIP_WAITING" in client.get("/sw.js").data.decode()


def test_sw_never_writes_runtime_cache(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "cache.put(" not in resp.data.decode()


# --- /offline ------------------------------------------------------------------------


def test_offline_page_returns_200(client):
    assert client.get("/offline").status_code == 200


def test_offline_page_has_offline_testid(client):
    assert 'data-testid="offline-page"' in client.get("/offline").data.decode()


def test_offline_page_omits_creator_identity(creator_client):
    resp = creator_client.get("/offline")
    assert resp.status_code == 200
    assert "Test Creator" not in resp.data.decode()


def test_offline_page_contains_no_csrf_token(creator_client):
    resp = creator_client.get("/offline")
    assert resp.status_code == 200
    assert "csrf" not in resp.data.decode()


def test_offline_page_is_translated_in_english(client):
    resp = client.get("/offline", headers={"Accept-Language": "en"})
    assert "You are offline" in resp.data.decode()


# --- Manifest and base markers --------------------------------------------------------


def test_manifest_scope_id_and_start_url_are_root():
    m = _manifest()
    assert (m.get("id"), m.get("scope"), m.get("start_url")) == ("/", "/", "/")


def test_manifest_has_no_orientation_lock():
    assert "orientation" not in _manifest()


def test_manifest_declares_shortcuts():
    assert [s["url"] for s in _manifest().get("shortcuts", [])] == ["/e/", "/e/new"]


def test_base_links_fingerprinted_manifest(client):
    html = client.get("/").data.decode()
    assert re.search(r'rel="manifest" href="/static/manifest\.json\?v=[0-9a-f]{10}"', html)


def test_base_marks_service_worker_enabled_by_default(client):
    assert 'data-sw="on"' in client.get("/").data.decode()


def test_base_marks_service_worker_disabled_by_config(app, client):
    app.config["SW_ENABLED"] = False
    assert 'data-sw="off"' in client.get("/").data.decode()


def test_legacy_service_worker_file_removed():
    assert not (REPO / "app/static/js/service-worker.js").exists()


def test_alpine_asset_removed():
    assert not (REPO / "app/static/js/alpine.min.js").exists()
