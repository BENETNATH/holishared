"""B017 — UI tooling: demo seed and demo server (spec §9.2, §9.3)."""

import importlib.util
import os
from pathlib import Path

import pytest

from app.extensions import limiter

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ui"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seeded(monkeypatch, tmp_path):
    """Isolated environment, tooling modules loaded, demo seeded in ``tmp_path``."""
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.setattr(limiter, "enabled", limiter.enabled)
    seed_demo = _load("seed_demo")
    serve_demo = _load("serve_demo")
    return seed_demo, serve_demo, seed_demo.seed(tmp_path)


def _loads(serve_demo, fixtures, cookie):
    app = serve_demo.build_app(fixtures)
    return app.session_interface.get_signing_serializer(app).loads(cookie)


def test_seed_demo_writes_cookies_for_every_authenticated_role(monkeypatch, tmp_path):
    _, _, fixtures = _seeded(monkeypatch, tmp_path)
    assert set(fixtures["cookies"]) == {"creator", "guest_household", "guest_solo"}


def test_seed_demo_creator_cookie_contains_only_login_keys(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    session = _loads(serve_demo, fixtures, fixtures["cookies"]["creator"])
    assert set(session) == {"_user_id", "_fresh"}


def test_seed_demo_guest_cookie_contains_only_guest_key(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    session = _loads(serve_demo, fixtures, fixtures["cookies"]["guest_household"])
    assert set(session) == {f"guest_{fixtures['placeholders']['event.rich']}"}


def test_seed_demo_creates_every_event_kind(monkeypatch, tmp_path):
    _, _, fixtures = _seeded(monkeypatch, tmp_path)
    assert {k for k in fixtures["placeholders"] if k.startswith("event.")} == {
        "event.rich",
        "event.empty",
        "event.full",
        "event.unverified",
        "event.past",
        "event.long",
    }


def test_seed_demo_full_event_reaches_guest_limit(monkeypatch, tmp_path):
    from app.freemium import can_add_guest
    from app.models import Event

    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    with serve_demo.build_app(fixtures).app_context():
        event = Event.query.filter_by(code=fixtures["placeholders"]["event.full"]).one()
        assert can_add_guest(event) is False


def test_seed_demo_unverified_event_has_no_verified_at(monkeypatch, tmp_path):
    from app.models import Event

    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    with serve_demo.build_app(fixtures).app_context():
        event = Event.query.filter_by(code=fixtures["placeholders"]["event.unverified"]).one()
        assert event.verified_at is None


def test_seed_demo_long_event_title_exceeds_80_chars(monkeypatch, tmp_path):
    from app.models import Event

    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    with serve_demo.build_app(fixtures).app_context():
        event = Event.query.filter_by(code=fixtures["placeholders"]["event.long"]).one()
        assert len(event.title) > 80


def test_seed_demo_writes_database_under_output_dir(monkeypatch, tmp_path):
    _, _, fixtures = _seeded(monkeypatch, tmp_path)
    assert Path(fixtures["database_path"]).is_relative_to(tmp_path.resolve())


def test_seed_demo_refuses_output_inside_repository(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    seed_demo = _load("seed_demo")
    with pytest.raises(ValueError, match="hors du dépôt"):
        seed_demo.seed(seed_demo.REPO_ROOT / "ui-demo")


def test_serve_demo_disables_rate_limiter(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    monkeypatch.setattr(limiter, "enabled", True)
    serve_demo.build_app(fixtures)
    assert limiter.enabled is False


def test_serve_demo_redirects_instance_path(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    assert serve_demo.build_app(fixtures).instance_path == fixtures["instance_path"]


def test_serve_demo_enables_ui_catalog(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    assert serve_demo.build_app(fixtures).config.get("UI_CATALOG_ENABLED") is True


def test_serve_demo_disables_smtp(monkeypatch, tmp_path):
    _, serve_demo, fixtures = _seeded(monkeypatch, tmp_path)
    assert serve_demo.build_app(fixtures).config["SMTP_HOST"] == ""
