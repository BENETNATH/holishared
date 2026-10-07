"""Démarrage : suppression d'événement avec votes, purge, étapes indépendantes (audit B018-B024 #1, #3)."""

import logging
from datetime import date, datetime, timedelta

from app.models import Event, Guest, Poll, PollOption, PollVote, generate_event_code
from app.startup import purge_expired_events, run_startup_steps


def _voted_event(db, creator, *, end=date(2026, 12, 7), verified=True):
    event = Event(
        code=generate_event_code(),
        title="Avec votes",
        start_date=date(2026, 12, 1),
        end_date=end,
        creator_id=creator.id,
        verified_at=datetime.utcnow() if verified else None,
        created_at=datetime.utcnow() - timedelta(days=10),
    )
    db.session.add(event)
    db.session.flush()
    voter = Guest(code=f"v{event.code}", display_name="Votant", event_id=event.id)
    poll = Poll(question="Q ?", event_id=event.id)
    db.session.add_all([voter, poll])
    db.session.flush()
    option = PollOption(label="A", order=0, poll_id=poll.id)
    db.session.add(option)
    db.session.flush()
    db.session.add(PollVote(option_id=option.id, guest_id=voter.id))
    db.session.commit()
    return event


def test_orm_delete_event_with_votes_removes_event(db, creator):
    event = _voted_event(db, creator)
    db.session.delete(event)
    db.session.commit()
    assert Event.query.filter_by(id=event.id).count() == 0


def test_orm_delete_event_with_votes_removes_votes(db, creator):
    event = _voted_event(db, creator)
    db.session.delete(event)
    db.session.commit()
    assert PollVote.query.count() == 0


def test_delete_route_event_with_votes_redirects_and_removes_event(creator_client, db, creator):
    event = _voted_event(db, creator)
    code, event_id = event.code, event.id
    resp = creator_client.post(f"/e/{code}/delete")
    assert (resp.status_code, Event.query.filter_by(id=event_id).count()) == (302, 0)


def test_purge_removes_expired_event_with_votes(app, db, creator):
    event = _voted_event(db, creator, end=date.today() - timedelta(days=40))
    event_id = event.id
    purge_expired_events(app)
    assert Event.query.filter_by(id=event_id).count() == 0


def test_purge_failure_on_one_event_does_not_block_the_next(app, db, creator, monkeypatch):
    first = _voted_event(db, creator, end=date.today() - timedelta(days=40))
    second = _voted_event(db, creator, end=date.today() - timedelta(days=41))
    first_id, second_id = first.id, second.id
    real_delete = db.session.delete

    def flaky(obj):
        if getattr(obj, "id", None) == first_id:
            raise RuntimeError("boom")
        return real_delete(obj)

    monkeypatch.setattr(db.session, "delete", flaky)
    purge_expired_events(app)
    monkeypatch.undo()
    assert Event.query.filter_by(id=second_id).count() == 0


def test_failing_step_does_not_prevent_next_steps(app, caplog):
    calls = []

    def boom(_app):
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        results = run_startup_steps(app, [("a", boom), ("b", lambda _app: calls.append("b"))])
    assert (results, calls) == ({"a": False, "b": True}, ["b"])


def test_failing_step_is_logged(app, caplog):
    def boom(_app):
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        run_startup_steps(app, [("a", boom)])
    assert "startup step a failed" in caplog.text


def test_skip_startup_env_runs_no_step(app, monkeypatch):
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    assert run_startup_steps(app, [("a", lambda _app: None)]) == {}


def test_skip_startup_env_does_not_purge(app, db, creator, monkeypatch):
    event = _voted_event(db, creator, end=date.today() - timedelta(days=40))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    run_startup_steps(app)
    assert Event.query.filter_by(id=event.id).count() == 1


def test_create_app_purges_expired_voted_event_then_runs_identity_migration(monkeypatch, tmp_path):
    from app import create_app
    from app.extensions import db as _db
    from app.models import Creator

    monkeypatch.setattr("app.load_dotenv", lambda *args, **kwargs: True)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("INSTANCE_PATH", str(tmp_path / "inst"))
    monkeypatch.setenv("SKIP_STARTUP_MIGRATION", "1")
    first = create_app()
    with first.app_context():
        creator = Creator(email="c@t.com", email_verified=True, display_name="C")
        _db.session.add(creator)
        _db.session.commit()
        _voted_event(_db, creator, end=date.today() - timedelta(days=40))
        current = _voted_event(_db, creator, end=date.today() + timedelta(days=5))
        current_id = current.id
        _db.session.remove()
    monkeypatch.delenv("SKIP_STARTUP_MIGRATION")
    second = create_app()
    with second.app_context():
        remaining = {e.id for e in Event.query.all()}
        creator_guests = (
            Guest.query.filter_by(event_id=current_id).filter(Guest.creator_id.isnot(None)).count()
        )
    assert (remaining, creator_guests) == ({current_id}, 1)
