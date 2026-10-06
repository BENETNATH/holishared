"""Tests du contexte d'événement (B029) : rôles x états."""

from datetime import datetime, timedelta

import pytest
from flask_login import login_user
from werkzeug.exceptions import HTTPException

from app.context import (
    CREATOR_FALLBACK_NAME,
    SYSTEM_ACTOR,
    Actor,
    get_event_context,
    get_or_create_creator_participant,
    load_event_context,
    reset_event_context,
)
from app.models import Guest, Household
from app.utils import ensure_creator_guest


def _ctx(app, code, *, creator=None, session=None, **kwargs):
    """Une « requête » simulée : contexte propre, cache vidé."""
    with app.test_request_context():
        from flask import session as flask_session

        reset_event_context()
        if creator is not None:
            login_user(creator)
        for key, value in (session or {}).items():
            flask_session[key] = value
        return load_event_context(code, **kwargs)


def _refusal(app, code, **kwargs):
    with pytest.raises(HTTPException) as exc:
        _ctx(app, code, **kwargs)
    return exc.value


def test_load_context_creator_logged_in_role_creator(app, event, creator):
    assert _ctx(app, event.code, creator=creator).role == "creator"


def test_load_context_creator_participant_linked_to_creator(app, event, creator):
    assert _ctx(app, event.code, creator=creator).participant.creator_id == creator.id


def test_load_context_creator_without_participant_creates_one_once(app, event, creator):
    _ctx(app, event.code, creator=creator)
    _ctx(app, event.code, creator=creator)
    assert Guest.query.filter_by(creator_id=creator.id, event_id=event.id).count() == 1


def test_load_context_creator_fallback_creates_no_household(app, event, creator):
    _ctx(app, event.code, creator=creator)
    assert Household.query.filter_by(event_id=event.id).count() == 0


def test_load_context_creator_existing_participant_reused(app, event, creator, creator_guest):
    assert _ctx(app, event.code, creator=creator).participant.id == creator_guest.id


def test_load_context_guest_session_role_guest(app, event, guest):
    assert _ctx(app, event.code, session={f"guest_{event.code}": guest.id}).role == "guest"


def test_load_context_guest_session_participant_is_guest(app, event, guest):
    ctx = _ctx(app, event.code, session={f"guest_{event.code}": guest.id})
    assert ctx.participant.id == guest.id


def test_load_context_creator_and_guest_session_creator_wins(app, event, creator, guest):
    ctx = _ctx(app, event.code, creator=creator, session={f"guest_{event.code}": guest.id})
    assert ctx.role == "creator"


def test_load_context_inactive_guest_redirects_mycode(app, db, event, guest):
    guest.is_active = False
    db.session.commit()
    exc = _refusal(app, event.code, session={f"guest_{event.code}": guest.id})
    assert exc.get_response().headers["Location"].endswith(f"/e/{event.code}/mycode")


def test_load_context_guest_of_other_event_redirects_mycode(app, db, event, creator, guest):
    from datetime import date

    from app.models import Event

    other = Event(
        code="zzzzzz",
        title="O",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 2),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    exc = _refusal(app, other.code, session={f"guest_{other.code}": guest.id})
    assert exc.get_response().status_code == 302


def test_load_context_session_pointing_creator_guest_ignored(app, event, creator_guest):
    exc = _refusal(app, event.code, session={f"guest_{event.code}": creator_guest.id})
    assert exc.get_response().status_code == 302


def test_load_context_anonymous_require_none_visitor(app, event):
    assert _ctx(app, event.code, require="none").role == "visitor"


def test_load_context_anonymous_redirects_mycode(app, event):
    exc = _refusal(app, event.code)
    assert exc.get_response().headers["Location"].endswith(f"/e/{event.code}/mycode")


def test_load_context_unknown_code_404(app):
    assert _refusal(app, "nope00").code == 404


def test_load_context_inactive_event_404(app, db, event):
    event.is_active = False
    db.session.commit()
    assert _refusal(app, event.code).code == 404


def test_load_context_unverified_event_404(app, unverified_event, creator):
    assert _refusal(app, unverified_event.code, creator=creator).code == 404


def test_load_context_unverified_event_require_none_404(app, unverified_event):
    assert _refusal(app, unverified_event.code, require="none").code == 404


def test_load_context_guest_require_creator_403(app, event, guest):
    exc = _refusal(app, event.code, session={f"guest_{event.code}": guest.id}, require="creator")
    assert exc.code == 403


def test_load_context_other_creator_require_creator_redirects_mycode(app, db, event):
    from app.models import Creator

    other = Creator(email="o@test.com", email_verified=True, display_name="O")
    db.session.add(other)
    db.session.commit()
    exc = _refusal(app, event.code, creator=other, require="creator")
    assert exc.get_response().status_code == 302


def test_load_context_second_call_returns_cached_object(app, event):
    with app.test_request_context():
        reset_event_context()
        first = load_event_context(event.code, require="none")
        assert load_event_context(event.code, require="none") is first


def test_actor_creator_uses_participant_name(app, event, creator, creator_guest):
    ctx = _ctx(app, event.code, creator=creator)
    assert ctx.actor == Actor("Test Creator", "creator", creator_guest.id)


def test_actor_guest_type_guest(app, event, guest):
    ctx = _ctx(app, event.code, session={f"guest_{event.code}": guest.id})
    assert ctx.actor.type == "guest"


def test_actor_visitor_is_system_actor(app, event):
    assert _ctx(app, event.code, require="none").actor == SYSTEM_ACTOR


def test_creator_participant_empty_display_name_uses_fallback(app, db, event, creator):
    creator.display_name = ""
    db.session.commit()
    assert _ctx(app, event.code, creator=creator).participant.display_name == CREATOR_FALLBACK_NAME


def test_ensure_creator_guest_reactivates_inactive_participant(
    app, db, event, creator, creator_guest
):
    creator_guest.is_active = False
    db.session.commit()
    again = ensure_creator_guest(event, creator, with_household=False)
    assert (again.id, again.is_active) == (creator_guest.id, True)


def test_ensure_creator_guest_without_household_flag_creates_none(app, event, creator):
    ensure_creator_guest(event, creator, with_household=False)
    assert Household.query.filter_by(event_id=event.id).count() == 0


def test_reset_event_context_clears_cached_context(app, event):
    with app.test_request_context():
        reset_event_context()
        load_event_context(event.code, require="none")
        reset_event_context()
        assert get_event_context() is None


def test_get_or_create_creator_participant_returns_oldest_on_duplicates(
    app, db, event, creator, creator_guest
):
    creator_guest.joined_at = datetime.utcnow() - timedelta(days=2)
    db.session.add(
        Guest(code="dup0000000000001", display_name="Dup", event_id=event.id, creator_id=creator.id)
    )
    db.session.commit()
    assert get_or_create_creator_participant(event, creator).id == creator_guest.id


def test_load_context_htmx_anonymous_returns_hx_redirect(app, event):
    with app.test_request_context(headers={"HX-Request": "true"}):
        reset_event_context()
        with pytest.raises(HTTPException) as exc:
            load_event_context(event.code)
    response = exc.value.get_response()
    assert (
        response.status_code,
        response.headers["HX-Redirect"].endswith(f"/e/{event.code}/mycode"),
    ) == (204, True)
