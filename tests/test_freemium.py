"""Tests for freemium limits."""

from datetime import date

from app.models import Event, Guest, generate_event_code, generate_guest_code


class TestGuestLimit:
    def test_can_add_guest_under_limit(self, db, event):
        from app.freemium import can_add_guest
        assert can_add_guest(event) is True

    def test_cannot_add_guest_at_limit(self, db, event, app):
        from app.freemium import can_add_guest
        app.config["MAX_GUESTS_PER_EVENT"] = 2
        for _ in range(2):
            g = Guest(code=generate_guest_code(), display_name="X", event_id=event.id)
            db.session.add(g)
        db.session.commit()
        assert can_add_guest(event) is False


class TestEventLimit:
    def test_can_create_event_under_limit(self, db, creator, app):
        from app.freemium import can_create_event
        assert can_create_event(creator) is True

    def test_cannot_create_event_at_limit(self, db, creator, app):
        from app.freemium import can_create_event
        app.config["MAX_EVENTS_PER_CREATOR"] = 1
        e = Event(
            code=generate_event_code(),
            title="E1",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            creator_id=creator.id,
        )
        db.session.add(e)
        db.session.commit()
        assert can_create_event(creator) is False
