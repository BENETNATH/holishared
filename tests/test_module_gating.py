"""Tests for module gating — disabled modules return 404 and hide their nav link.

Covers the requirement: when a (premium) module is not activated in
ENABLED_MODULES, its route must not be reachable and its navigation link must
not be rendered, to avoid broken links / orphaned routes.
"""

import pytest

from app.extensions import db as _db


@pytest.fixture
def gated_app(monkeypatch):
    """App with only planning + lists enabled (media/costs disabled)."""
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("ENABLED_MODULES", "planning,lists")
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


def _seed(app):
    from datetime import date

    from app.models import Creator, Event, generate_event_code

    c = Creator(email="g@t.com", email_verified=True, display_name="C")
    _db.session.add(c)
    _db.session.commit()
    e = Event(
        code=generate_event_code(), title="V",
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 7),
        creator_id=c.id,
    )
    _db.session.add(e)
    _db.session.commit()
    return c, e


def _client(app, creator):
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = creator.id
        s["_fresh"] = True
    return client


def test_disabled_module_returns_404(gated_app):
    c, e = _seed(gated_app)
    client = _client(gated_app, c)
    assert client.get(f"/e/{e.code}/media").status_code == 404
    assert client.get(f"/e/{e.code}/costs").status_code == 404
    assert client.get(f"/e/{e.code}/planning").status_code == 200
    assert client.get(f"/e/{e.code}/lists").status_code == 200


def test_nav_hides_disabled_modules(gated_app):
    import re

    c, e = _seed(gated_app)
    client = _client(gated_app, c)
    html = client.get(f"/e/{e.code}").data.decode()
    # Navigation bureau : data-testid="nav-desktop"
    nav = re.search(r'<nav[^>]*data-testid="nav-desktop".*?</nav>', html, re.S).group(0)
    assert "Media" not in nav
    assert "Frais" not in nav
    assert "Planning" in nav
    assert "Listes" in nav
