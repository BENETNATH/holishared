"""Tests for planning blueprint — B003.

44 tests, déterministes, un comportement = un test.
Ces tests DOIVENT échouer avant le codage (TDD).
"""

from datetime import date, time
from app.models import Activity, ActivityRSVP, ActivityLog, Guest, generate_guest_code


# === Fixtures locales (complètent conftest.py) ===

import pytest


@pytest.fixture
def other_guest(db, event):
    """Un second guest sur le même événement."""
    g = Guest(
        code=generate_guest_code(),
        display_name="Other Guest",
        event_id=event.id,
    )
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def activity(db, event):
    """Une activité dans la période de l'événement."""
    a = Activity(
        title="Swimming",
        description="Pool party",
        date=date(2026, 12, 3),
        start_time=time(14, 0),
        end_time=time(16, 0),
        location="Pool",
        min_headcount=3,
        bring_items="Maillots",
        event_id=event.id,
    )
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def activity_rsvp(db, activity, guest):
    """Un RSVP 'yes' du guest sur l'activité."""
    r = ActivityRSVP(
        status="yes",
        activity_id=activity.id,
        guest_id=guest.id,
    )
    db.session.add(r)
    db.session.commit()
    return r


def _login_creator(client, creator):
    """Helper : simule le login du créateur."""
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True


def _login_guest(client, event, guest):
    """Helper : simule la session d'un guest."""
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id


# === TestPlanningIndex (10 tests) ===


class TestPlanningIndex:
    def test_index_renders_for_creator(self, client, creator, event, activity):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning")
        assert resp.status_code == 200
        assert b"Swimming" in resp.data

    def test_index_renders_for_guest(self, client, event, guest, activity):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/planning")
        assert resp.status_code == 200
        assert b"Swimming" in resp.data

    def test_index_404_for_invalid_code(self, client, creator):
        _login_creator(client, creator)
        resp = client.get("/e/xxxxxx/planning")
        assert resp.status_code == 404

    def test_index_redirects_if_no_access(self, client, event):
        resp = client.get(f"/e/{event.code}/planning")
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]

    def test_index_shows_activities_sorted(self, client, creator, event, db):
        _login_creator(client, creator)
        a1 = Activity(title="B Activity", date=date(2026, 12, 5), event_id=event.id)
        a2 = Activity(title="A Activity", date=date(2026, 12, 2), event_id=event.id)
        db.session.add_all([a1, a2])
        db.session.commit()
        resp = client.get(f"/e/{event.code}/planning")
        data = resp.data
        assert data.index(b"A Activity") < data.index(b"B Activity")

    def test_index_shows_empty_message(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning")
        assert b"Aucune activit" in resp.data

    def test_index_shows_confirmed_count(self, client, creator, event, activity, activity_rsvp):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning")
        assert b"1/3" in resp.data

    def test_index_shows_insufficient_badge(self, client, creator, event, activity, activity_rsvp):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning")
        assert b"insufficient" in resp.data

    def test_index_shows_rsvp_status(self, client, event, guest, activity, activity_rsvp):
        _login_guest(client, event, guest)
        resp = client.get(f"/e/{event.code}/planning")
        assert b'aria-pressed="true"' in resp.data

    def test_index_inactive_event_404(self, client, creator, event):
        _login_creator(client, creator)
        event.is_active = False
        from app.extensions import db as _db
        _db.session.commit()
        resp = client.get(f"/e/{event.code}/planning")
        assert resp.status_code == 404


# === TestCreateActivity (13 tests) ===


class TestCreateActivity:
    def test_create_get_renders_form(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning/new")
        assert resp.status_code == 200
        assert b'name="title"' in resp.data
        assert b'name="date"' in resp.data

    def test_create_success_as_creator(self, client, creator, event, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Hiking",
            "description": "Mountain trail",
            "date": "2026-12-04",
            "start_time": "09:00",
            "end_time": "12:00",
            "location": "Vosges",
            "min_headcount": "2",
            "bring_items": "Eau",
        })
        assert resp.status_code == 302
        act = Activity.query.filter_by(title="Hiking").first()
        assert act is not None
        assert act.created_by is None

    def test_create_success_as_guest(self, client, event, guest, db):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Beach",
            "date": "2026-12-05",
        })
        assert resp.status_code == 302
        act = Activity.query.filter_by(title="Beach").first()
        assert act is not None
        assert act.created_by == guest.id

    def test_create_missing_title(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "",
            "date": "2026-12-04",
        })
        assert resp.status_code == 200
        assert b"Titre requis" in resp.data

    def test_create_title_too_short(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "A",
            "date": "2026-12-04",
        })
        assert resp.status_code == 200
        assert b"Titre requis" in resp.data

    def test_create_description_too_long(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "description": "x" * 2001,
            "date": "2026-12-04",
        })
        assert resp.status_code == 200
        assert b"Description trop longue" in resp.data

    def test_create_date_outside_event(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "date": "2026-11-01",
        })
        assert resp.status_code == 200
        assert b"hors de la p" in resp.data  # "hors de la période"

    def test_create_end_before_start(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "date": "2026-12-04",
            "start_time": "16:00",
            "end_time": "14:00",
        })
        assert resp.status_code == 200
        assert b"Heure de fin avant" in resp.data

    def test_create_location_too_long(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "date": "2026-12-04",
            "location": "x" * 301,
        })
        assert resp.status_code == 200
        assert b"Lieu trop long" in resp.data

    def test_create_min_headcount_out_of_range(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "date": "2026-12-04",
            "min_headcount": "0",
        })
        assert resp.status_code == 200
        assert b"Nombre entre 1 et 50" in resp.data

    def test_create_bring_items_too_long(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Test",
            "date": "2026-12-04",
            "bring_items": "x" * 501,
        })
        assert resp.status_code == 200
        assert b"Champ trop long" in resp.data

    def test_create_logs_activity(self, client, creator, event, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/planning/new", data={
            "title": "Logged Act",
            "date": "2026-12-04",
        })
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="activity.created"
        ).first()
        assert log is not None
        assert log.target == "Logged Act"
        assert log.actor_type == "creator"

    def test_create_redirects_to_index(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/new", data={
            "title": "Redirect Test",
            "date": "2026-12-04",
        })
        assert resp.status_code == 302
        assert f"/e/{event.code}/planning" in resp.headers["Location"]


# === TestEditActivity (7 tests) ===


class TestEditActivity:
    def test_edit_get_renders_prefilled(self, client, creator, event, activity):
        _login_creator(client, creator)
        resp = client.get(f"/e/{event.code}/planning/{activity.id}/edit")
        assert resp.status_code == 200
        assert b"Swimming" in resp.data
        assert b"Pool" in resp.data

    def test_edit_success_as_creator(self, client, creator, event, activity, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/edit", data={
            "title": "Updated Swimming",
            "description": "New desc",
            "date": "2026-12-04",
            "start_time": "10:00",
            "end_time": "12:00",
            "location": "New Pool",
            "min_headcount": "5",
            "bring_items": "Towels",
        })
        assert resp.status_code == 302
        db.session.refresh(activity)
        assert activity.title == "Updated Swimming"
        assert activity.location == "New Pool"

    def test_edit_success_as_activity_creator(self, client, event, guest, db):
        # Guest crée une activité
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/planning/new", data={
            "title": "Guest Activity",
            "date": "2026-12-04",
        })
        act = Activity.query.filter_by(title="Guest Activity").first()
        # Guest modifie sa propre activité
        resp = client.post(f"/e/{event.code}/planning/{act.id}/edit", data={
            "title": "Guest Activity v2",
            "date": "2026-12-05",
        })
        assert resp.status_code == 302
        db.session.refresh(act)
        assert act.title == "Guest Activity v2"

    def test_edit_forbidden_for_other_guest(self, client, event, guest, other_guest, activity):
        # other_guest n'a pas créé l'activité
        _login_guest(client, event, other_guest)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/edit", data={
            "title": "Hacked",
            "date": "2026-12-04",
        })
        assert resp.status_code == 403

    def test_edit_404_for_invalid_id(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/invalid_id/edit", data={
            "title": "Test",
            "date": "2026-12-04",
        })
        assert resp.status_code == 404

    def test_edit_404_for_invalid_code(self, client, creator, activity):
        _login_creator(client, creator)
        resp = client.post(f"/e/badcode/planning/{activity.id}/edit", data={
            "title": "Test",
            "date": "2026-12-04",
        })
        assert resp.status_code == 404

    def test_edit_logs_activity(self, client, creator, event, activity, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/planning/{activity.id}/edit", data={
            "title": "Logged Edit",
            "date": "2026-12-04",
        })
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="activity.updated"
        ).first()
        assert log is not None
        assert log.target == "Logged Edit"


# === TestDeleteActivity (6 tests) ===


class TestDeleteActivity:
    def test_delete_success_as_creator(self, client, creator, event, activity, db):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/delete")
        assert resp.status_code == 302
        assert Activity.query.get(activity.id) is None

    def test_delete_success_as_activity_creator(self, client, event, guest, db):
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/planning/new", data={
            "title": "To Delete",
            "date": "2026-12-04",
        })
        act = Activity.query.filter_by(title="To Delete").first()
        resp = client.post(f"/e/{event.code}/planning/{act.id}/delete")
        assert resp.status_code == 302
        assert Activity.query.get(act.id) is None

    def test_delete_forbidden_for_other_guest(self, client, event, other_guest, activity):
        _login_guest(client, event, other_guest)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/delete")
        assert resp.status_code == 403

    def test_delete_cascades_rsvps(self, client, creator, event, activity, activity_rsvp, db):
        _login_creator(client, creator)
        assert ActivityRSVP.query.get(activity_rsvp.id) is not None
        client.post(f"/e/{event.code}/planning/{activity.id}/delete")
        assert ActivityRSVP.query.get(activity_rsvp.id) is None

    def test_delete_404_for_invalid_id(self, client, creator, event):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/invalid_id/delete")
        assert resp.status_code == 404

    def test_delete_logs_activity(self, client, creator, event, activity, db):
        _login_creator(client, creator)
        client.post(f"/e/{event.code}/planning/{activity.id}/delete")
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="activity.deleted"
        ).first()
        assert log is not None
        assert log.target == "Swimming"


# === TestRSVP (9 tests) ===


class TestRSVP:
    def test_rsvp_yes(self, client, event, guest, activity, db):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "yes",
        })
        assert resp.status_code == 302
        rsvp = ActivityRSVP.query.filter_by(
            activity_id=activity.id, guest_id=guest.id
        ).first()
        assert rsvp is not None
        assert rsvp.status == "yes"

    def test_rsvp_no(self, client, event, guest, activity, db):
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "no",
        })
        rsvp = ActivityRSVP.query.filter_by(
            activity_id=activity.id, guest_id=guest.id
        ).first()
        assert rsvp.status == "no"

    def test_rsvp_maybe(self, client, event, guest, activity, db):
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "maybe",
        })
        rsvp = ActivityRSVP.query.filter_by(
            activity_id=activity.id, guest_id=guest.id
        ).first()
        assert rsvp.status == "maybe"

    def test_rsvp_update_existing(self, client, event, guest, activity, activity_rsvp, db):
        _login_guest(client, event, guest)
        assert activity_rsvp.status == "yes"
        client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "no",
        })
        db.session.refresh(activity_rsvp)
        assert activity_rsvp.status == "no"

    def test_rsvp_invalid_status(self, client, event, guest, activity):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "xyz",
        }, follow_redirects=True)
        assert b"Statut invalide" in resp.data

    def test_rsvp_forbidden_for_creator(self, client, creator, event, activity):
        _login_creator(client, creator)
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "yes",
        }, follow_redirects=True)
        assert b"cr" in resp.data.lower()  # "Le créateur ne fait pas de RSVP"

    def test_rsvp_redirects_if_not_logged_in(self, client, event, activity):
        resp = client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "yes",
        })
        assert resp.status_code == 302
        assert "/mycode" in resp.headers["Location"]

    def test_rsvp_404_for_invalid_activity(self, client, event, guest):
        _login_guest(client, event, guest)
        resp = client.post(f"/e/{event.code}/planning/invalid_id/rsvp", data={
            "status": "yes",
        })
        assert resp.status_code == 404

    def test_rsvp_logs_activity(self, client, event, guest, activity, db):
        _login_guest(client, event, guest)
        client.post(f"/e/{event.code}/planning/{activity.id}/rsvp", data={
            "status": "yes",
        })
        log = ActivityLog.query.filter_by(
            event_id=event.id, action="rsvp.updated"
        ).first()
        assert log is not None
        assert log.target == "Swimming"
        assert log.details == "yes"
        assert log.actor_type == "guest"
