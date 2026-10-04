"""Test fixtures for holishared."""

import pytest
from app import create_app
from app.extensions import db as _db
from app.models import Creator, Event, Guest, generate_event_code, generate_guest_code


@pytest.fixture
def app():
    """Create a test app with in-memory SQLite."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
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
    """An active event."""
    from datetime import date
    e = Event(
        code=generate_event_code(),
        title="Test Vacation",
        description="A test event",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        location="Strasbourg",
        creator_id=creator.id,
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
