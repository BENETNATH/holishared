"""Tests HTTP du contexte d'événement (B029) : réponses homogènes, en-tête."""

from datetime import date, datetime

from app.models import Creator, Event, Guest, ListItem, SharedList


def _location(resp) -> str:
    return str(resp.headers["Location"])


def test_dashboard_unknown_event_404(creator_client):
    assert creator_client.get("/e/nope00").status_code == 404


def test_join_unknown_event_404(client):
    assert client.get("/e/nope00/join").status_code == 404


def test_mycode_unverified_event_404(client, unverified_event):
    assert client.get(f"/e/{unverified_event.code}/mycode").status_code == 404


def test_join_unverified_event_404(client, unverified_event):
    assert client.get(f"/e/{unverified_event.code}/join").status_code == 404


def test_dashboard_unverified_event_creator_404(creator_client, unverified_event):
    assert creator_client.get(f"/e/{unverified_event.code}").status_code == 404


def test_verify_sent_unverified_event_200(client, unverified_event):
    assert client.get(f"/e/new/sent/{unverified_event.code}").status_code == 200


def test_join_with_guest_session_redirects_dashboard(guest_client, event):
    resp = guest_client.get(f"/e/{event.code}/join")
    assert _location(resp).endswith(f"/e/{event.code}")


def test_join_post_as_creator_creates_no_guest(creator_client, event, creator_guest):
    before = Guest.query.count()
    creator_client.post(f"/e/{event.code}/join", data={"display_name": "Zed", "code": "zed12345"})
    assert Guest.query.count() == before


def test_mycode_with_participant_redirects_dashboard(guest_client, event):
    resp = guest_client.get(f"/e/{event.code}/mycode")
    assert _location(resp).endswith(f"/e/{event.code}")


def test_log_anonymous_redirects_mycode(client, event):
    assert "/mycode" in _location(client.get(f"/e/{event.code}/log"))


def test_log_unknown_event_renders_404_template(creator_client):
    assert b'data-testid="error-404"' in creator_client.get("/e/nope00/log").data


def test_invite_guest_403(guest_client, event):
    assert guest_client.get(f"/e/{event.code}/invite").status_code == 403


def test_invite_anonymous_redirects_mycode(client, event):
    assert "/mycode" in _location(client.get(f"/e/{event.code}/invite"))


def test_invite_qr_unverified_event_404(client, unverified_event):
    assert client.get(f"/e/{unverified_event.code}/invite/qr").status_code == 404


def test_export_anonymous_redirects_mycode(client, event):
    assert "/mycode" in _location(client.get(f"/e/{event.code}/export"))


def test_export_pdf_other_creator_redirects_mycode(client, db, event):
    other = Creator(email="o@test.com", email_verified=True, display_name="O", tier="pro")
    db.session.add(other)
    db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = other.id
        sess["_fresh"] = True
    assert "/mycode" in _location(client.get(f"/e/{event.code}/export/pdf"))


def test_invite_inactive_event_404(db, creator_client, event):
    event.is_active = False
    db.session.commit()
    assert creator_client.get(f"/e/{event.code}/invite").status_code == 404


def _built_client(app_factory, modules: str):
    built = app_factory({"ENABLED_MODULES": modules})
    from app.extensions import db

    creator = Creator(email="b029@test.com", email_verified=True, display_name="Camille")
    db.session.add(creator)
    db.session.commit()
    event = Event(
        code="abc234",
        title="Gated",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    client = built.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = creator.id
        sess["_fresh"] = True
    return client, event


def test_app_factory_verified_event_planning_renders_for_creator(app_factory):
    client, event = _built_client(app_factory, "planning,voting,chat")
    assert client.get(f"/e/{event.code}/planning").status_code == 200


def test_app_factory_no_module_verified_event_members_renders(app_factory):
    client, event = _built_client(app_factory, "")
    assert client.get(f"/e/{event.code}/members").status_code == 200


def test_dashboard_my_items_matched_by_id(db, guest_client, event, guest):
    shared = SharedList(title="L", event_id=event.id)
    db.session.add(shared)
    db.session.flush()
    db.session.add(
        ListItem(name="Zz-mine", assigned_to="Autre", assigned_to_id=guest.id, list_id=shared.id)
    )
    db.session.commit()
    assert b"Zz-mine" in guest_client.get(f"/e/{event.code}").data


def test_members_remove_creator_participant_403(creator_client, event, creator_guest):
    resp = creator_client.post(
        f"/e/{event.code}/members", data={"action": "remove", "guest_id": creator_guest.id}
    )
    assert (resp.status_code, creator_guest.is_active) == (403, True)


def test_dashboard_creator_get_creates_no_household(creator_client, event):
    from app.models import Household

    creator_client.get(f"/e/{event.code}")
    assert Household.query.filter_by(event_id=event.id).count() == 0
