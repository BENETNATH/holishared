"""B019 (F01) — « Mes événements » pour les invités : liste dérivée des sessions de l'appareil."""

from datetime import date, datetime

import pytest

from app.models import Creator, Event, Guest, generate_event_code


def _make_event(db, creator, title, verified=True):
    e = Event(
        code=generate_event_code(),
        title=title,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 7),
        creator_id=creator.id,
        verified_at=datetime.utcnow() if verified else None,
    )
    db.session.add(e)
    db.session.commit()
    return e


def _guest(db, event, code="gst12345"):
    g = Guest(code=code, display_name="Invité", event_id=event.id)
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture
def other_event(db):
    other = Creator(email="other@test.com", display_name="Other")
    db.session.add(other)
    db.session.commit()
    return _make_event(db, other, "Autre événement")


def _open(client, guests):
    with client.session_transaction() as sess:
        for g in guests:
            sess[f"guest_{g.event.code}"] = g.id
    return client.get("/e/")


def _titles(html):
    import re

    return re.findall(r'data-testid="event-card-link"[^>]*>([^<]*)<', html)


def test_guest_without_creator_login_gets_events_page(client, event, guest):
    assert _open(client, [guest]).status_code == 200


def test_guest_sees_event_of_the_device(client, event, guest):
    assert _titles(_open(client, [guest]).get_data(as_text=True)) == [event.title]


def test_guest_sees_each_event_joined_on_the_device(client, db, event, guest, other_event):
    g2 = _guest(db, other_event)
    assert sorted(_titles(_open(client, [guest, g2]).get_data(as_text=True))) == sorted(
        [event.title, other_event.title]
    )


def test_guest_does_not_see_events_of_another_session(app, db, event, guest, other_event):
    mine = app.test_client()
    _open(mine, [guest])
    theirs = app.test_client()
    html = _open(theirs, [_guest(db, other_event)]).get_data(as_text=True)
    assert event.title not in html


def test_guest_session_pointing_to_other_events_guest_is_ignored(client, db, event, other_event):
    foreign = _guest(db, other_event)
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = foreign.id
    assert client.get("/e/").status_code == 302


def test_deactivated_guest_event_is_not_listed(client, db, event, guest):
    guest.is_active = False
    db.session.commit()
    assert _open(client, [guest]).status_code == 302


def test_unverified_event_is_not_listed_for_guest(client, db, creator, unverified_event):
    g = _guest(db, unverified_event)
    assert _open(client, [g]).status_code == 302


def test_device_without_any_access_is_redirected_home(client):
    assert client.get("/e/").headers["Location"] == "/"


def test_redirect_home_explains_why_with_a_toast(client):
    html = client.get("/e/", follow_redirects=True).get_data(as_text=True)
    assert 'data-tone="info"' in html


def test_creator_sees_only_own_verified_events(creator_client, db, creator, event, other_event):
    _make_event(db, creator, "Pas confirmé", verified=False)
    assert _titles(creator_client.get("/e/").get_data(as_text=True)) == [event.title]


def test_creator_with_no_event_sees_empty_state_not_redirect(creator_client):
    assert creator_client.get("/e/").status_code == 200


def test_guest_events_page_offers_forget_device(client, event, guest):
    html = _open(client, [guest]).get_data(as_text=True)
    assert 'data-testid="forget-device"' in html


def test_forget_device_button_posts_to_logout(client, event, guest):
    html = _open(client, [guest]).get_data(as_text=True)
    assert 'action="/admin/logout"' in html


def test_bottom_nav_shows_my_events_tab_for_guest_device_on_landing(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id
    html = client.get("/").get_data(as_text=True)
    assert 'data-testid="tab-events"' in html


def test_bottom_nav_hides_my_events_tab_for_unknown_device(client):
    assert 'data-testid="tab-events"' not in client.get("/").get_data(as_text=True)
