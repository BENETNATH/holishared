"""Test fixtures for holishared."""

import secrets
from datetime import date, datetime

import pytest

from app import create_app
from app.extensions import db as _db
from app.extensions import limiter
from app.models import Creator, Event, Guest, generate_event_code, generate_guest_code


@pytest.fixture
def app(monkeypatch):
    """Create a test app with in-memory SQLite.

    Flask-SQLAlchemy 3.1 crée le moteur dans ``init_app()`` (appelé par
    ``create_app``), donc la URI doit être fixée via l'env AVANT la
    création de l'app. ``load_dotenv`` est désactivé pour que le ``.env``
    de dev (override=True) n'écrase pas ``DATABASE_URL``.
    """
    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    # Le .env de développement ne doit pas influencer les réglages testés (B019).
    for name in ("PERMANENT_SESSION_LIFETIME", "DEV_SHOW_SECRETS"):
        monkeypatch.delenv(name, raising=False)
    # Enable every module so blueprint-gated routes exist in tests.
    monkeypatch.setenv(
        "ENABLED_MODULES", "planning,meals,lists,logistics,voting,media,chat,costs"
    )
    app = create_app()
    limiter.reset()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SUPERADMIN_EMAIL"] = "admin@test.com"
    app.config["SUPERADMIN_PASSWORD"] = "testpass"
    app.config["SMTP_HOST"] = ""  # No email in tests

    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def creator(db):
    """A verified creator."""
    c = Creator(
        email="creator@test.com",
        email_verified=True,
        display_name="Test Creator",
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture
def event(db, creator):
    """An active, verified event."""
    e = Event(
        code=generate_event_code(),
        title="Test Vacation",
        description="A test event",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        location="Strasbourg",
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def unverified_event(db, creator, event):
    """Same as ``event`` but never verified (other code, same creator)."""
    e = Event(
        code=generate_event_code(),
        title="Unverified Vacation",
        description="Not verified yet",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        location="Strasbourg",
        creator_id=creator.id,
        verified_at=None,
    )
    db.session.add(e)
    db.session.commit()
    return e


@pytest.fixture
def guest(db, event):
    """An active guest on the event."""
    g = Guest(
        code=generate_guest_code(),
        display_name="Test Guest",
        event_id=event.id,
    )
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def creator_guest(db, event, creator):
    """The creator's participant identity (``Guest.creator_id`` set)."""
    g = Guest(
        code=secrets.token_hex(8),
        display_name="Test Creator",
        event_id=event.id,
        creator_id=creator.id,
    )
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def other_guest_c(db, event):
    """A second active guest, distinct from ``guest``."""
    g = Guest(code=generate_guest_code(), display_name="Other Guest", event_id=event.id)
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def creator_client(client, creator):
    """Test client logged in as the creator (B017)."""
    with client.session_transaction() as s:
        s["_user_id"] = creator.id
        s["_fresh"] = True
    return client


@pytest.fixture
def guest_client(client, event, guest):
    """Test client identified as the guest of the event (B017)."""
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = guest.id
    return client


@pytest.fixture
def app_factory(monkeypatch):
    """Build apps from a custom environment (B017).

    ``build(env)`` sets ``DATABASE_URL=sqlite:///:memory:`` plus ``env``, calls
    ``create_app()``, pushes an app context and creates the tables.
    """
    contexts = []

    def build(env: dict[str, str]):
        monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        for name in ("PERMANENT_SESSION_LIFETIME", "DEV_SHOW_SECRETS"):
            monkeypatch.delenv(name, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        application = create_app()
        application.config["TESTING"] = True
        application.config["WTF_CSRF_ENABLED"] = False
        ctx = application.app_context()
        ctx.push()
        contexts.append(ctx)
        _db.create_all()
        return application

    yield build
    for ctx in reversed(contexts):
        _db.drop_all()
        ctx.pop()
