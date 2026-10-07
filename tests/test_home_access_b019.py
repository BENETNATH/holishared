"""B019 — accueil : un champ « code », chemins clairs, « Vos événements », erreurs neutres."""

import re

import pytest

from app.models import Creator, Guest


def _post(client, code):
    return client.post("/e/access", data={"code": code})


def _error(resp):
    html = resp.get_data(as_text=True)
    match = re.search(r'data-testid="err-code".*?</p>', html, re.S)
    return match.group(0) if match else None


@pytest.fixture
def six(db, creator):
    creator.personal_code = "abc123"
    db.session.commit()
    return creator


def test_landing_offers_create_path(client):
    assert 'data-testid="landing-create"' in client.get("/").get_data(as_text=True)


def test_landing_offers_single_code_field_labelled_your_code(client):
    html = client.get("/").get_data(as_text=True)
    assert html.count('name="code"') == 1


def test_landing_code_field_does_not_force_eight_characters(client):
    assert "pattern=" not in client.get("/").get_data(as_text=True).split('name="code"')[1][:300]


def test_landing_links_to_forgotten_code(client):
    assert 'data-testid="forgot-code"' in client.get("/").get_data(as_text=True)


@pytest.mark.parametrize("length", [4, 5, 6, 7, 8])
def test_creator_code_of_any_length_logs_in(app, db, creator, length):
    creator.personal_code = "a1b2c3d4e5"[:length]
    db.session.commit()
    client = app.test_client()
    _post(client, creator.personal_code)
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == creator.id


def test_creator_code_is_case_insensitive(app, six):
    client = app.test_client()
    _post(client, " ABC123 ")
    with client.session_transaction() as sess:
        assert sess.get("_user_id") == six.id


def test_creator_code_login_goes_to_my_events(client, six):
    assert _post(client, "abc123").headers["Location"].endswith("/e/")


def test_event_code_goes_to_event_access_page(client, event):
    assert _post(client, event.code).headers["Location"] == f"/e/{event.code}/mycode"


@pytest.mark.parametrize("bad", ["ab", "zzzzzzzz", "abcdefghijk", "ab cd!", "<b>x</b>"])
def test_refused_code_renders_inline_error_with_status_200(client, bad):
    assert _post(client, bad).status_code == 200


@pytest.mark.parametrize("bad", ["ab", "zzzzzzzz", "abcdefghijk", "ab cd!"])
def test_every_refused_code_gets_the_same_message(client, six, bad):
    assert _error(_post(client, bad)) == _error(_post(client, "qqqqqqqq"))


def test_unverified_event_code_gets_the_neutral_message(client, unverified_event):
    unknown = _error(_post(client, "qqqqqq"))
    assert _error(_post(client, unverified_event.code)) == unknown


def test_guest_personal_code_gets_the_neutral_message(client, guest):
    assert _error(_post(client, guest.code)) == _error(_post(client, "qqqqqqqq"))


def test_refused_code_message_does_not_say_whether_code_exists(client):
    assert "existe" not in _error(_post(client, "zzzzzzzz")).lower()


def test_refused_code_keeps_what_was_typed(client):
    assert 'value="zzzz12"' in _post(client, "zzzz12").get_data(as_text=True)


def test_refused_code_page_is_still_the_landing_page(client):
    assert 'data-testid="landing-create"' in _post(client, "zzzz12").get_data(as_text=True)


def test_landing_hides_your_events_for_unknown_device(client):
    assert 'data-testid="landing-events"' not in client.get("/").get_data(as_text=True)


def test_landing_shows_your_events_for_guest_device(client, event, guest):
    with client.session_transaction() as sess:
        sess[f"guest_{event.code}"] = guest.id
    html = client.get("/").get_data(as_text=True)
    assert f'href="/e/{event.code}"' in html


def test_landing_shows_your_events_for_creator(creator_client, event):
    assert 'data-testid="landing-events"' in creator_client.get("/").get_data(as_text=True)


def test_landing_does_not_show_events_of_other_creators(client, db, event):
    other = Creator(email="o@test.com", display_name="O")
    db.session.add(other)
    db.session.commit()
    assert event.title not in client.get("/").get_data(as_text=True)


def test_landing_shows_at_most_three_events(creator_client, db, creator, event):
    from tests.test_device_events_b019 import _make_event

    for n in range(4):
        _make_event(db, creator, f"Extra {n}")
    assert creator_client.get("/").get_data(as_text=True).count('data-testid="event-card"') == 3


def test_guest_row_untouched_by_failed_code(client, db, guest):
    _post(client, "zzzzzzzz")
    assert Guest.query.count() == 1
