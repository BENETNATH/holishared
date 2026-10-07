"""B027 — service worker : gestionnaires push (analyse du contenu servi, sans navigateur)."""

import re


def _sw(client) -> str:
    return client.get("/sw.js").data.decode()


def test_sw_registers_push_handler(client):
    assert "addEventListener('push'" in _sw(client)


def test_sw_registers_notificationclick_handler(client):
    assert "addEventListener('notificationclick'" in _sw(client)


def test_sw_registers_notificationclose_handler(client):
    assert "addEventListener('notificationclose'" in _sw(client)


def test_sw_push_icon_is_the_192_icon(client):
    assert 'const PUSH_ICON = "/static/icons/icon-192.png"' in _sw(client)


def test_sw_push_sets_badge(client):
    assert "badge: PUSH_ICON" in _sw(client)


def test_sw_push_sets_renotify_only_with_a_tag(client):
    body = _sw(client)
    assert re.search(r"if \(data\.tag\) \{[^}]*renotify", body) is not None


def test_sw_click_focuses_an_open_window_before_opening_one(client):
    body = _sw(client)
    assert body.index("client.focus()") < body.index("clients.openWindow")


def test_sw_notification_url_is_restricted_to_same_origin(client):
    assert "origin === self.location.origin" in _sw(client)


def test_sw_cache_name_changes_with_the_service_worker_template(app, monkeypatch):
    from pathlib import Path

    from app import ui

    with app.test_request_context():
        before = ui.asset_version()
        real = Path.read_bytes
        monkeypatch.setattr(
            Path, "read_bytes", lambda self: real(self) + (b"x" if self.name == "sw.js" else b"")
        )
        assert ui.asset_version() != before
