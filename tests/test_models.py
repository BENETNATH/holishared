"""Tests for models."""

from app.models import (
    ActivityLog,
    generate_event_code,
    generate_guest_code,
)


class TestCodeGeneration:
    def test_event_code_length(self):
        code = generate_event_code()
        assert len(code) == 6

    def test_event_code_alphabet(self):
        code = generate_event_code()
        assert code.islower() or code.isdigit() or (code.isalnum() and code.islower())

    def test_event_code_unique(self):
        codes = {generate_event_code() for _ in range(100)}
        assert len(codes) == 100

    def test_guest_code_length(self):
        code = generate_guest_code()
        assert len(code) == 8

    def test_guest_code_unique(self):
        codes = {generate_guest_code() for _ in range(100)}
        assert len(codes) == 100


class TestEvent:
    def test_duration_days(self, event):
        assert event.duration_days == 7

    def test_guest_count_empty(self, event):
        assert event.guest_count == 0

    def test_guest_count_with_guest(self, event, guest):
        assert event.guest_count == 1


class TestActivityLog:
    def test_log_creation(self, db, event):
        log = ActivityLog(
            event_id=event.id,
            actor_name="Test",
            actor_type="guest",
            action="activity.created",
            target="Swimming",
        )
        db.session.add(log)
        db.session.commit()
        assert log.id is not None
        assert log.created_at is not None
